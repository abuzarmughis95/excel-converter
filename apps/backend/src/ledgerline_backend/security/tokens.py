"""Access (JWT) and refresh (opaque) token helpers.

Access tokens are short-lived signed JWTs carrying the user id (``sub``) and no
PII. Refresh tokens are opaque high-entropy strings; only their SHA-256 hash is
ever stored, so the database never holds a usable token.

``now`` is injectable on the time-sensitive functions to make expiry testable
without sleeping.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import secrets
import uuid

import jwt

from ledgerline_backend.config import Settings
from ledgerline_backend.util.time import utcnow


class TokenError(Exception):
    """Raised when a token is invalid, expired, or malformed."""


# Backwards-compatible alias for the shared helper.
_utcnow = utcnow


def create_access_token(
    settings: Settings,
    user_id: uuid.UUID,
    *,
    now: dt.datetime | None = None,
) -> str:
    """Create a signed, short-lived access JWT for a user."""
    issued = now or _utcnow()
    expires = issued + dt.timedelta(seconds=settings.access_token_ttl_seconds)
    claims = {
        "sub": str(user_id),
        "iat": int(issued.timestamp()),
        "exp": int(expires.timestamp()),
        "typ": "access",
    }
    return jwt.encode(claims, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(
    settings: Settings,
    token: str,
    *,
    now: dt.datetime | None = None,
) -> uuid.UUID:
    """Decode and validate an access token, returning the user id.

    Raises :class:`TokenError` if the token is expired, malformed, signed with
    the wrong key, or not an access token.
    """
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            options={"require": ["exp", "iat", "sub"]},
            leeway=0,
        )
    except jwt.PyJWTError as exc:
        raise TokenError(str(exc)) from exc

    if payload.get("typ") != "access":
        raise TokenError("not an access token")
    try:
        return uuid.UUID(str(payload["sub"]))
    except (KeyError, ValueError) as exc:
        raise TokenError("invalid subject") from exc


def generate_refresh_token() -> str:
    """Generate a high-entropy opaque refresh token string."""
    return secrets.token_urlsafe(48)


def hash_refresh_token(token: str) -> str:
    """Return the hex SHA-256 hash of a refresh token (what we persist)."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def refresh_token_expiry(settings: Settings, *, now: dt.datetime | None = None) -> dt.datetime:
    """Compute the absolute expiry for a newly-issued refresh token."""
    return (now or _utcnow()) + dt.timedelta(seconds=settings.refresh_token_ttl_seconds)
