"""Top-level Typer application for the `insighta` CLI."""

from __future__ import annotations

import sys

import httpx
import typer

from insighta import __version__
from insighta.commands import auth_cmd
from insighta.commands.profiles_cmd import profiles_app
from insighta.errors import InsightaError, render_error

app = typer.Typer(
    name="insighta",
    help="Insighta Labs CLI \u2014 manage profiles and authenticate with GitHub.",
    no_args_is_help=True,
    add_completion=False,
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"insighta {__version__}")
        raise typer.Exit()


@app.callback()
def _root(
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        help="Show the CLI version and exit.",
        callback=_version_callback,
        is_eager=True,
    ),
) -> None:
    """Insighta Labs CLI."""


# Auth commands are exposed at the top level: `insighta login|logout|whoami`.
app.command("login", help="Sign in to Insighta via GitHub.")(auth_cmd.login)
app.command("logout", help="Sign out and clear stored credentials.")(auth_cmd.logout)
app.command("whoami", help="Show the currently signed-in user.")(auth_cmd.whoami)

app.add_typer(profiles_app, name="profiles")


def main() -> None:
    try:
        app()
    except InsightaError as exc:
        render_error(exc)
        sys.exit(1)
    except httpx.HTTPError as exc:
        render_error(InsightaError(f"Network error: {exc}"))
        sys.exit(1)


if __name__ == "__main__":
    main()
