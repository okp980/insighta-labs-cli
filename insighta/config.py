"""Runtime configuration constants for the CLI."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


def _load_dotenv_layers() -> None:
    """Load layered ``.env`` files into ``os.environ`` (later layers override).

    1. ``~/.insighta/.env`` for machine-local defaults beside credentials.
    2. ``./.env`` in ``Path.cwd()`` with ``override=True`` so repo/project wins.
    """

    insighta_home = Path.home() / ".insighta"
    load_dotenv(insighta_home / ".env")

    cwd_env = Path.cwd() / ".env"
    load_dotenv(cwd_env, override=True)


_load_dotenv_layers()

X_API_VERSION: str = os.environ.get("INSIGHTA_API_VERSION", "1")

CRED_DIR: Path = Path.home() / ".insighta"
CRED_PATH: Path = CRED_DIR / "credentials.json"

DEFAULT_TIMEOUT_SECONDS: float = 30.0
LOGIN_TIMEOUT_SECONDS: float = 300.0

# Env key for backend base URL (no default baked into code --- use ``.env`` or env).
INSIGHTA_API_URL_VAR: str = "INSIGHTA_API_URL"
