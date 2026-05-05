"""HTTP client for the Insighta backend.

Handles:
- cookie-based auth (the API reads ``access_token`` / ``refresh_token`` from cookies),
- CSRF double-submit (cookie ``csrf_token`` plus ``X-CSRF-Token`` header on
  state-changing requests),
- the required ``X-API-Version`` header for ``/api/*`` routes,
- transparent token refresh on 401 with a single retry, and
- consistent error extraction from the backend's ``{status, message}`` envelope.
"""

from __future__ import annotations

import os
import secrets
from typing import Any, Iterator, Mapping

import httpx

from insighta.config import DEFAULT_TIMEOUT_SECONDS, INSIGHTA_API_URL_VAR, X_API_VERSION
from insighta.credentials import (
    Credentials,
    clear_credentials,
    load_credentials,
    save_credentials,
    update_tokens,
)
from insighta.errors import (
    InsightaApiError,
    InsightaAuthError,
    InsightaError,
    extract_error_message,
)

UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _normalize_backend_base(url: str) -> str:
    return url.strip().rstrip("/")


def _resolve_backend_base_url(
    explicit: str | None,
    creds: Credentials | None,
) -> str:
    if explicit and explicit.strip():
        return _normalize_backend_base(explicit)
    env = os.environ.get(INSIGHTA_API_URL_VAR, "").strip()
    if env:
        return _normalize_backend_base(env)
    if creds and creds.api_base_url and creds.api_base_url.strip():
        return _normalize_backend_base(creds.api_base_url)
    raise InsightaError(
        "Backend URL is not configured.",
        hint=(
            f"Set {INSIGHTA_API_URL_VAR} in the environment, or in `.env` "
            "in the current directory, or `~/.insighta/.env`. "
            "Copy `.env.example` to `.env` for a local template. "
            "If you are already logged in but this error persists, "
            "set the variable and run `insighta login` again."
        ),
    )


class ApiClient:
    """Thin wrapper around ``httpx.Client`` that knows how to talk to Insighta."""

    def __init__(self, base_url: str | None = None, timeout: float = DEFAULT_TIMEOUT_SECONDS):
        self._csrf_token = secrets.token_urlsafe(32)
        self._creds = load_credentials()
        self.base_url = _resolve_backend_base_url(base_url, self._creds)
        self._client = httpx.Client(base_url=self.base_url, timeout=timeout)

    # ------------------------------------------------------------------
    # context manager
    # ------------------------------------------------------------------
    def __enter__(self) -> "ApiClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    # ------------------------------------------------------------------
    # credential helpers
    # ------------------------------------------------------------------
    @property
    def credentials(self) -> Credentials | None:
        return self._creds

    def set_credentials(self, creds: Credentials, *, persist: bool = True) -> None:
        self._creds = creds
        if persist:
            save_credentials(creds)

    def clear(self) -> None:
        self._creds = None
        clear_credentials()

    # ------------------------------------------------------------------
    # request helpers
    # ------------------------------------------------------------------
    def _build_cookies(self, *, authenticated: bool, include_csrf: bool) -> dict[str, str]:
        cookies: dict[str, str] = {}
        if authenticated and self._creds is not None:
            cookies["access_token"] = self._creds.access_token
            cookies["refresh_token"] = self._creds.refresh_token
        if include_csrf:
            cookies["csrf_token"] = self._csrf_token
        return cookies

    def _build_headers(
        self,
        *,
        path: str,
        method: str,
        extra: Mapping[str, str] | None = None,
    ) -> dict[str, str]:
        headers: dict[str, str] = {"Accept": "application/json"}
        if path.startswith("/api/"):
            headers["X-API-Version"] = X_API_VERSION
        if method.upper() in UNSAFE_METHODS:
            headers["X-CSRF-Token"] = self._csrf_token
        if extra:
            headers.update(extra)
        return headers

    def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Any | None = None,
        data: Any | None = None,
        headers: Mapping[str, str] | None = None,
        authenticated: bool = True,
        allow_refresh: bool = True,
        stream: bool = False,
    ) -> httpx.Response:
        method_u = method.upper()
        include_csrf = method_u in UNSAFE_METHODS
        cookies = self._build_cookies(authenticated=authenticated, include_csrf=include_csrf)
        merged_headers = self._build_headers(path=path, method=method_u, extra=headers)

        if stream:
            req = self._client.build_request(
                method_u,
                path,
                params=params,
                json=json,
                data=data,
                headers=merged_headers,
                cookies=cookies,
            )
            response = self._client.send(req, stream=True)
        else:
            response = self._client.request(
                method_u,
                path,
                params=params,
                json=json,
                data=data,
                headers=merged_headers,
                cookies=cookies,
            )

        if (
            response.status_code == 401
            and authenticated
            and allow_refresh
            and self._creds is not None
        ):
            if stream:
                response.close()
            refreshed = self._try_refresh()
            if refreshed:
                return self.request(
                    method,
                    path,
                    params=params,
                    json=json,
                    data=data,
                    headers=headers,
                    authenticated=authenticated,
                    allow_refresh=False,
                    stream=stream,
                )

        return response

    # ------------------------------------------------------------------
    # token refresh
    # ------------------------------------------------------------------
    def _try_refresh(self) -> bool:
        if self._creds is None:
            return False
        cookies = {
            "refresh_token": self._creds.refresh_token,
            "csrf_token": self._csrf_token,
        }
        headers = {"Accept": "application/json", "X-CSRF-Token": self._csrf_token}
        try:
            r = self._client.post("/auth/refresh", cookies=cookies, headers=headers)
        except httpx.HTTPError:
            return False

        if r.status_code != 200:
            self._handle_session_lost()
            return False

        body = self._safe_json(r)
        access = body.get("access_token") if isinstance(body, dict) else None
        refresh = body.get("refresh_token") if isinstance(body, dict) else None
        if not access or not refresh:
            # fall back to cookies if any
            access = r.cookies.get("access_token") or access
            refresh = r.cookies.get("refresh_token") or refresh
        if not access or not refresh:
            self._handle_session_lost()
            return False

        self._creds = update_tokens(access, refresh)
        return True

    def _handle_session_lost(self) -> None:
        self._creds = None
        try:
            clear_credentials()
        except InsightaError:
            pass

    # ------------------------------------------------------------------
    # JSON helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _safe_json(response: httpx.Response) -> Any:
        try:
            return response.json()
        except ValueError:
            return None

    def _raise_for_status(self, response: httpx.Response) -> None:
        if response.is_success:
            return
        body = self._safe_json(response)
        message = extract_error_message(body, fallback=response.reason_phrase or "Request failed")
        if response.status_code == 401:
            raise InsightaAuthError(
                "Session expired or invalid.",
                status=401,
                hint="Run `insighta login` to sign in again.",
            )
        if response.status_code == 403:
            raise InsightaApiError(
                message or "Permission denied.",
                status=403,
                hint="Your account role may not allow this action.",
            )
        raise InsightaApiError(message, status=response.status_code)

    # ------------------------------------------------------------------
    # convenience
    # ------------------------------------------------------------------
    def get_json(
        self,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        authenticated: bool = True,
    ) -> Any:
        r = self.request("GET", path, params=params, authenticated=authenticated)
        self._raise_for_status(r)
        return self._safe_json(r)

    def post_json(
        self,
        path: str,
        *,
        json: Any | None = None,
        authenticated: bool = True,
    ) -> Any:
        r = self.request("POST", path, json=json, authenticated=authenticated)
        self._raise_for_status(r)
        return self._safe_json(r)

    def stream(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        authenticated: bool = True,
    ) -> "_StreamCtx":
        return _StreamCtx(self, method, path, params=params, authenticated=authenticated)


class _StreamCtx:
    """Context manager that opens a streaming response with refresh-on-401."""

    def __init__(
        self,
        client: ApiClient,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None,
        authenticated: bool,
    ) -> None:
        self._client = client
        self._method = method
        self._path = path
        self._params = params
        self._authenticated = authenticated
        self._response: httpx.Response | None = None

    def __enter__(self) -> httpx.Response:
        response = self._client.request(
            self._method,
            self._path,
            params=self._params,
            authenticated=self._authenticated,
            stream=True,
        )
        if not response.is_success:
            try:
                response.read()
            finally:
                response.close()
            self._client._raise_for_status(response)  # type: ignore[attr-defined]
        self._response = response
        return response

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._response is not None:
            self._response.close()


def iter_bytes(response: httpx.Response, chunk_size: int = 8192) -> Iterator[bytes]:
    yield from response.iter_bytes(chunk_size=chunk_size)
