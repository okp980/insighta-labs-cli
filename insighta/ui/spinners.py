"""Shared Rich consoles and spinner helpers."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from rich.console import Console
from rich.status import Status

console: Console = Console()
err_console: Console = Console(stderr=True)


@contextmanager
def loader(message: str) -> Iterator[Status]:
    with console.status(message, spinner="dots") as status:
        yield status
