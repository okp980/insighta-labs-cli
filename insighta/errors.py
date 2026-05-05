"""Error types and consistent error rendering for the CLI."""

from __future__ import annotations

from typing import Any

from rich.console import Console

_err_console = Console(stderr=True)


class InsightaError(Exception):
    """Base error raised for all expected CLI failures."""

    def __init__(self, message: str, *, status: int | None = None, hint: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.hint = hint


class InsightaAuthError(InsightaError):
    """Raised when the user is not authenticated or the session has expired."""


class InsightaApiError(InsightaError):
    """Raised when the backend returns a non-success response."""


def render_error(err: BaseException) -> None:
    if isinstance(err, InsightaError):
        prefix = f"[bold red]Error[/]"
        if err.status is not None:
            prefix += f" [dim]({err.status})[/]"
        _err_console.print(f"{prefix}: {err.message}")
        if err.hint:
            _err_console.print(f"[yellow]Hint:[/] {err.hint}")
    else:
        _err_console.print(f"[bold red]Unexpected error[/]: {err}")


def extract_error_message(payload: Any, fallback: str) -> str:
    if isinstance(payload, dict):
        for key in ("message", "detail", "error", "error_description"):
            value = payload.get(key)
            if isinstance(value, str) and value:
                return value
    return fallback
