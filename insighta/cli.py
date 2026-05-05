"""Top-level Typer application for the `insighta` CLI."""

from __future__ import annotations

import sys

import typer

from insighta import __version__
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


def main() -> None:
    try:
        app()
    except InsightaError as exc:
        render_error(exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
