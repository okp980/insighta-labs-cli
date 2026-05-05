"""Runtime configuration constants for the CLI."""

from __future__ import annotations

import os
from pathlib import Path

API_BASE_URL: str = os.environ.get("INSIGHTA_API_URL", "http://localhost:8000").rstrip("/")

X_API_VERSION: str = os.environ.get("INSIGHTA_API_VERSION", "1")

CRED_DIR: Path = Path.home() / ".insighta"
CRED_PATH: Path = CRED_DIR / "credentials.json"

DEFAULT_TIMEOUT_SECONDS: float = 30.0
LOGIN_TIMEOUT_SECONDS: float = 300.0
