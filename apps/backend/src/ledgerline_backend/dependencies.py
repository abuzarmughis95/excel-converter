"""FastAPI dependency providers.

Settings are resolved from application state (set by the app factory) rather
than the module-level cache, so each app instance reflects the configuration it
was built with. This keeps endpoints testable with isolated settings.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session, sessionmaker

from ledgerline_backend.config import Settings
from ledgerline_backend.models import User
from ledgerline_backend.security.rate_limit import SlidingWindowRateLimiter
from ledgerline_backend.security.tokens import TokenError, decode_access_token
from ledgerline_backend.services.hmrc_client import HmrcClient, HttpHmrcClient


def get_app_settings(request: Request) -> Settings:
    """Return the Settings bound to the running application instance."""
    settings = request.app.state.settings
    assert isinstance(settings, Settings)  # noqa: S101 — invariant, set by factory
    return settings


def get_session_factory(request: Request) -> sessionmaker[Session]:
    """Return the session factory bound to the running application instance."""
    factory = request.app.state.session_factory
    assert isinstance(factory, sessionmaker)  # noqa: S101 — invariant, set by factory
    return factory


def get_db_session(
    factory: Annotated[sessionmaker[Session], Depends(get_session_factory)],
) -> Iterator[Session]:
    """Yield a request-scoped session, committing on success, rolling back on error."""
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_login_rate_limiter(request: Request) -> SlidingWindowRateLimiter:
    """Return the shared login rate limiter bound to the application."""
    limiter = request.app.state.login_rate_limiter
    assert isinstance(limiter, SlidingWindowRateLimiter)  # noqa: S101 — set by factory
    return limiter


def get_client_ip(request: Request) -> str:
    """Best-effort client IP for throttling.

    Uses the direct peer address. Behind a trusted proxy this should be replaced
    with a validated X-Forwarded-For parser; left simple here to avoid trusting
    spoofable headers by default.
    """
    if request.client is not None:
        return request.client.host
    return "unknown"


SettingsDep = Annotated[Settings, Depends(get_app_settings)]
SessionDep = Annotated[Session, Depends(get_db_session)]
RateLimiterDep = Annotated[SlidingWindowRateLimiter, Depends(get_login_rate_limiter)]
ClientIpDep = Annotated[str, Depends(get_client_ip)]


def get_hmrc_client(settings: SettingsDep) -> HmrcClient:
    """Provide a configured HMRC client, or raise 503 if not configured.

    Tests override this dependency with a fake client, so HMRC is fully testable
    without live credentials.
    """
    from fastapi import HTTPException, status  # local import to avoid cycles

    if not settings.hmrc_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="HMRC MTD is not configured on the server",
        )
    assert settings.hmrc_client_id is not None  # noqa: S101 — guaranteed by hmrc_enabled
    assert settings.hmrc_client_secret is not None  # noqa: S101
    return HttpHmrcClient(
        base_url=settings.hmrc_base_url,
        client_id=settings.hmrc_client_id,
        client_secret=settings.hmrc_client_secret,
        redirect_uri=settings.hmrc_redirect_uri,
    )


HmrcClientDep = Annotated[HmrcClient, Depends(get_hmrc_client)]


def get_current_user(
    request: Request,
    settings: SettingsDep,
    session: SessionDep,
) -> User:
    """Resolve the authenticated user from the Bearer access token.

    Raises 401 if the header is missing/malformed, the token is invalid/expired,
    or the user no longer exists or is inactive.
    """
    from fastapi import HTTPException, status  # local import to avoid cycles

    header = request.headers.get("Authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        user_id: uuid.UUID = decode_access_token(settings, token)
    except TokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    user = session.get(User, user_id)
    if user is None or user.status != "active":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


CurrentUserDep = Annotated[User, Depends(get_current_user)]
