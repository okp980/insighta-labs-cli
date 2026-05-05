"""Read/write/clear `~/.insighta/credentials.json` with strict permissions."""

from __future__ import annotations

import json
import os
import stat
from typing import Any

from pydantic import BaseModel, ValidationError

from insighta.config import CRED_DIR, CRED_PATH
from insighta.errors import InsightaError


class StoredUser(BaseModel):
    id: str | None = None
    github_id: int | None = None
    username: str | None = None
    email: str | None = None
    avatar_url: str | None = None
    role: str | None = None
    is_active: bool | None = None


class Credentials(BaseModel):
    access_token: str
    refresh_token: str
    user: StoredUser | None = None
    api_base_url: str | None = None


def _ensure_dir() -> None:
    CRED_DIR.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(CRED_DIR, stat.S_IRWXU)
    except OSError:
        # On platforms that don't support chmod (e.g. Windows) we silently skip.
        pass


def load_credentials() -> Credentials | None:
    if not CRED_PATH.exists():
        return None
    try:
        raw: Any = json.loads(CRED_PATH.read_text(encoding="utf-8"))
        return Credentials.model_validate(raw)
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        raise InsightaError(
            f"Could not read credentials at {CRED_PATH}: {exc}",
            hint="Run `insighta login` to recreate them.",
        ) from exc


def require_credentials() -> Credentials:
    creds = load_credentials()
    if creds is None:
        raise InsightaError(
            "You are not logged in.",
            hint="Run `insighta login` first.",
        )
    return creds


def save_credentials(creds: Credentials) -> None:
    _ensure_dir()
    payload = creds.model_dump(exclude_none=True)
    data = json.dumps(payload, indent=2, sort_keys=True)

    tmp_path = CRED_PATH.with_suffix(".json.tmp")
    tmp_path.write_text(data, encoding="utf-8")
    try:
        os.chmod(tmp_path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
    os.replace(tmp_path, CRED_PATH)


def update_tokens(access_token: str, refresh_token: str) -> Credentials:
    existing = load_credentials()
    if existing is None:
        new = Credentials(access_token=access_token, refresh_token=refresh_token)
    else:
        new = existing.model_copy(
            update={"access_token": access_token, "refresh_token": refresh_token}
        )
    save_credentials(new)
    return new


def clear_credentials() -> None:
    if CRED_PATH.exists():
        try:
            CRED_PATH.unlink()
        except OSError as exc:
            raise InsightaError(f"Could not remove {CRED_PATH}: {exc}") from exc
