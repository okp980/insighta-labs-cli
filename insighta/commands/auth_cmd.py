"""`login`, `logout`, `whoami` subcommands."""

from __future__ import annotations

import typer

from insighta.api_client import ApiClient
from insighta.auth.flow import run_login_flow
from insighta.credentials import clear_credentials, load_credentials, require_credentials
from insighta.errors import InsightaApiError, InsightaError
from insighta.ui.spinners import console, err_console, loader


def login() -> None:
    """Authenticate with GitHub via the local PKCE flow."""
    existing = load_credentials()
    if existing is not None and existing.user and existing.user.username:
        console.print(
            f"[yellow]You are already signed in as[/] [bold]@{existing.user.username}[/]."
        )
        console.print(
            "Continuing will replace the saved credentials. "
            "Run [bold]insighta logout[/] first to cancel."
        )

    with ApiClient() as client:
        with loader("Starting GitHub OAuth flow...") as status:
            def _on_open(url: str) -> None:
                status.update("Waiting for GitHub authorization in your browser...")
                console.print(
                    "If your browser does not open automatically, visit:\n"
                    f"[cyan underline]{url}[/]"
                )

            result = run_login_flow(client, on_open_url=_on_open)

    user = result.user
    handle = f"@{user.username}" if user.username else "<unknown user>"
    role = f" ({user.role})" if user.role else ""
    console.print(f"[green]\u2713[/] Logged in as [bold]{handle}[/]{role}.")


def logout() -> None:
    """Revoke the current session and clear stored credentials."""
    creds = load_credentials()
    if creds is None:
        console.print("[yellow]You are not signed in.[/]")
        return

    with ApiClient() as client:
        try:
            with loader("Signing out..."):
                client.post_json("/auth/logout")
        except InsightaApiError as exc:
            err_console.print(
                f"[yellow]Warning:[/] backend reported {exc.status} \u2014 "
                "removing local credentials anyway."
            )
        finally:
            try:
                clear_credentials()
            except InsightaError as exc:
                err_console.print(f"[red]Could not remove local credentials:[/] {exc.message}")
                raise typer.Exit(code=1) from exc

    console.print("[green]\u2713[/] Signed out.")


def whoami() -> None:
    """Show the currently signed-in user."""
    require_credentials()
    with ApiClient() as client:
        with loader("Fetching account..."):
            payload = client.get_json("/auth/me")

    if not isinstance(payload, dict):
        raise InsightaError("Unexpected response from /auth/me.")
    data = payload.get("data") or {}
    username = data.get("username")
    email = data.get("email")
    role = data.get("role")
    if not username:
        raise InsightaError("Backend response did not include a username.")

    handle = f"@{username}"
    extras: list[str] = []
    if role:
        extras.append(f"role={role}")
    if email:
        extras.append(f"email={email}")
    suffix = f"  [dim]({', '.join(extras)})[/]" if extras else ""
    console.print(f"[bold]{handle}[/]{suffix}")
