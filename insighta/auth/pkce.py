"""PKCE primitives (RFC 7636) and OAuth state generation."""

from __future__ import annotations

import base64
import hashlib
import secrets


def _b64url_no_pad(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def generate_state(num_bytes: int = 24) -> str:
    """Return an opaque, URL-safe random string used as OAuth `state`."""
    return secrets.token_urlsafe(num_bytes)


def generate_code_verifier(num_bytes: int = 64) -> str:
    """Return a high-entropy code verifier.

    RFC 7636 specifies a minimum length of 43 and a maximum of 128 characters
    drawn from the unreserved URL-safe set ``A-Z / a-z / 0-9 / - / . / _ / ~``.
    ``secrets.token_urlsafe`` produces values from a compatible alphabet
    (``-`` and ``_`` only, no ``.`` or ``~``) which is acceptable.
    """
    return secrets.token_urlsafe(num_bytes)


def code_challenge_s256(verifier: str) -> str:
    """Compute the S256 PKCE code challenge for ``verifier``."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return _b64url_no_pad(digest)
