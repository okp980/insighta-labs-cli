"""GitHub OAuth (PKCE) login flow for the Insighta CLI.

The CLI:
 1. asks the backend for the GitHub OAuth ``client_id`` and ``redirect_uri``,
 2. generates a fresh ``state`` + PKCE pair,
 3. binds a loopback HTTP server on the redirect port,
 4. opens GitHub's authorize page in the user's browser,
 5. captures the ``?code=&state=`` redirect on the loopback,
 6. POSTs ``{code, code_verifier, state}`` to ``/auth/cli/exchange`` and
    persists the returned tokens.
"""

from __future__ import annotations

import http.server
import socket
import socketserver
import threading
import urllib.parse
import webbrowser
from dataclasses import dataclass
from typing import Any

from insighta.api_client import ApiClient
from insighta.auth.pkce import (
    code_challenge_s256,
    generate_code_verifier,
    generate_state,
)
from insighta.config import LOGIN_TIMEOUT_SECONDS
from insighta.credentials import Credentials, StoredUser, save_credentials
from insighta.errors import InsightaAuthError

GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"

_SUCCESS_HTML = b"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Insighta CLI - Login Successful</title>
<style>
  body { font-family: -apple-system, system-ui, sans-serif; background:#0f172a;
         color:#e2e8f0; display:flex; align-items:center; justify-content:center;
         min-height:100vh; margin:0; }
  .card { max-width: 480px; padding: 32px 36px; background:#1e293b;
          border-radius: 12px; box-shadow: 0 10px 30px rgba(0,0,0,.35); }
  h1 { margin-top: 0; font-size: 20px; }
  p { line-height: 1.5; }
  code { background:#0f172a; padding:2px 6px; border-radius:4px; }
</style>
</head>
<body>
  <div class="card">
    <h1>You're signed in.</h1>
    <p>Insighta CLI received your GitHub authorization.</p>
    <p>You can close this tab and return to your terminal.</p>
  </div>
</body>
</html>
"""

_ERROR_HTML_TEMPLATE = b"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Insighta CLI - Login Failed</title>
<style>
  body { font-family: -apple-system, system-ui, sans-serif; background:#0f172a;
         color:#fecaca; display:flex; align-items:center; justify-content:center;
         min-height:100vh; margin:0; }
  .card { max-width: 480px; padding: 32px 36px; background:#1e293b;
          border-radius: 12px; box-shadow: 0 10px 30px rgba(0,0,0,.35); }
  h1 { margin-top: 0; font-size: 20px; color:#fca5a5; }
  pre { background:#0f172a; padding:12px; border-radius:6px; color:#e2e8f0;
        overflow-x:auto; }
</style>
</head>
<body>
  <div class="card">
    <h1>Login failed</h1>
    <p>%s</p>
    <p>You can close this tab and return to your terminal.</p>
  </div>
</body>
</html>
"""


@dataclass
class _CallbackResult:
    code: str | None = None
    state: str | None = None
    error: str | None = None


def _make_handler(result: _CallbackResult, expected_state: str, done: threading.Event):
    class _Handler(http.server.BaseHTTPRequestHandler):
        # Silence default access logging.
        def log_message(self, format: str, *args: Any) -> None:  # noqa: A003 - stdlib name
            return

        def do_GET(self) -> None:  # noqa: N802 - stdlib API
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path != "/callback":
                self.send_response(404)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write(b"Not Found")
                return

            params = urllib.parse.parse_qs(parsed.query)
            error = params.get("error", [None])[0]
            error_description = params.get("error_description", [None])[0]
            code = params.get("code", [None])[0]
            state = params.get("state", [None])[0]

            if error:
                msg = error_description or error
                result.error = msg
                self._respond_html(400, _ERROR_HTML_TEMPLATE % msg.encode("utf-8", "replace"))
                done.set()
                return

            if not code or not state:
                result.error = "GitHub did not return a code or state."
                self._respond_html(400, _ERROR_HTML_TEMPLATE % result.error.encode("utf-8"))
                done.set()
                return

            if state != expected_state:
                result.error = "OAuth state mismatch \u2014 possible CSRF attack."
                self._respond_html(400, _ERROR_HTML_TEMPLATE % result.error.encode("utf-8"))
                done.set()
                return

            result.code = code
            result.state = state
            self._respond_html(200, _SUCCESS_HTML)
            done.set()

        def _respond_html(self, status: int, body: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return _Handler


class _ReusableTCPServer(socketserver.TCPServer):
    allow_reuse_address = True


def _parse_redirect_uri(redirect_uri: str) -> tuple[str, int]:
    parsed = urllib.parse.urlparse(redirect_uri)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port
    if port is None:
        raise InsightaAuthError(
            f"Invalid redirect_uri from server: {redirect_uri!r} (no port).",
            hint="Ensure GITHUB_CLI_REDIRECT_URI on the backend includes a port.",
        )
    if host not in {"127.0.0.1", "localhost"}:
        raise InsightaAuthError(
            f"Refusing to bind non-loopback host {host!r}.",
            hint="The CLI redirect URI must use 127.0.0.1 or localhost.",
        )
    return host, port


def _build_authorize_url(
    *,
    client_id: str,
    redirect_uri: str,
    state: str,
    code_challenge: str,
    scope: str,
) -> str:
    qs = urllib.parse.urlencode(
        {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": scope,
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
    )
    return f"{GITHUB_AUTHORIZE_URL}?{qs}"


@dataclass
class LoginResult:
    credentials: Credentials
    user: StoredUser


def run_login_flow(client: ApiClient, *, on_open_url=None) -> LoginResult:
    """Run the full PKCE login flow against the configured backend.

    ``on_open_url(url)`` is called once just before opening the browser so the
    UI layer can print a fallback link.
    """
    start_payload = client.get_json("/auth/cli/start", authenticated=False)
    if not isinstance(start_payload, dict):
        raise InsightaAuthError("Unexpected response from /auth/cli/start.")

    client_id = start_payload.get("client_id")
    redirect_uri = start_payload.get("redirect_uri")
    scope = start_payload.get("scope") or "user:email"
    if not client_id or not redirect_uri:
        raise InsightaAuthError(
            "Backend did not return CLI OAuth configuration.",
            hint="Set GITHUB_CLI_CLIENT_ID and GITHUB_CLI_REDIRECT_URI in the backend env.",
        )

    host, port = _parse_redirect_uri(redirect_uri)

    state = generate_state()
    code_verifier = generate_code_verifier()
    code_challenge = code_challenge_s256(code_verifier)

    auth_url = _build_authorize_url(
        client_id=client_id,
        redirect_uri=redirect_uri,
        state=state,
        code_challenge=code_challenge,
        scope=scope,
    )

    result = _CallbackResult()
    done = threading.Event()
    handler_cls = _make_handler(result, expected_state=state, done=done)

    try:
        server = _ReusableTCPServer((host, port), handler_cls)
    except OSError as exc:
        raise InsightaAuthError(
            f"Could not bind loopback callback on {host}:{port}: {exc}",
            hint=(
                "Another process is using that port. "
                "Stop it or change GITHUB_CLI_REDIRECT_URI on the backend."
            ),
        ) from exc

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        if on_open_url is not None:
            on_open_url(auth_url)
        try:
            webbrowser.open(auth_url, new=1, autoraise=True)
        except webbrowser.Error:
            # Browser not available (headless); the caller should print the URL.
            pass

        if not done.wait(timeout=LOGIN_TIMEOUT_SECONDS):
            raise InsightaAuthError(
                "Login timed out waiting for the GitHub redirect.",
                hint="Re-run `insighta login` and complete authorization in the browser.",
            )
    finally:
        server.shutdown()
        server.server_close()

    if result.error or not result.code:
        raise InsightaAuthError(result.error or "GitHub did not return an authorization code.")

    payload = client.post_json(
        "/auth/cli/exchange",
        json={
            "code": result.code,
            "code_verifier": code_verifier,
            "state": result.state,
        },
        authenticated=False,
    )

    if not isinstance(payload, dict):
        raise InsightaAuthError("Unexpected response from /auth/cli/exchange.")

    access_token = payload.get("access_token")
    refresh_token = payload.get("refresh_token")
    user_payload = payload.get("user") or {}

    if not access_token or not refresh_token:
        raise InsightaAuthError(
            "Backend did not return tokens.",
            hint="Check the backend logs for /auth/cli/exchange errors.",
        )

    user = StoredUser(
        id=str(user_payload.get("id")) if user_payload.get("id") is not None else None,
        github_id=user_payload.get("github_id"),
        username=user_payload.get("username"),
        email=user_payload.get("email"),
        avatar_url=user_payload.get("avatar_url"),
        role=user_payload.get("role"),
        is_active=user_payload.get("is_active"),
    )
    creds = Credentials(
        access_token=access_token,
        refresh_token=refresh_token,
        user=user,
        api_base_url=client.base_url,
    )
    save_credentials(creds)
    client.set_credentials(creds, persist=False)
    return LoginResult(credentials=creds, user=user)


def _is_port_free(host: str, port: int) -> bool:  # pragma: no cover - utility
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


__all__ = ["run_login_flow", "LoginResult"]
