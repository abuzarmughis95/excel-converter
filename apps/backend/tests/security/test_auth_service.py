"""Tests for the AuthService use-cases."""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, StaticPool, create_engine, select
from sqlalchemy.orm import Session

from ledgerline_backend import models  # noqa: F401 — register models
from ledgerline_backend.config import Settings
from ledgerline_backend.db.base import Base
from ledgerline_backend.models import Organisation, RefreshToken, UserCredential
from ledgerline_backend.security.auth_service import (
    AccountInactiveError,
    AccountLockedError,
    AuthService,
    DuplicateEmailError,
    InvalidCredentialsError,
    InvalidRefreshTokenError,
    UnknownOrganisationError,
)


@pytest.fixture
def engine() -> Iterator[Engine]:
    eng = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(eng)
    try:
        yield eng
    finally:
        eng.dispose()


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    with Session(engine) as db:
        yield db


@pytest.fixture
def settings() -> Settings:
    return Settings(
        environment="test",
        jwt_secret="test-secret",
        max_failed_logins=3,
        lockout_seconds=300,
    )


@pytest.fixture
def org(session: Session) -> Organisation:
    o = Organisation(name="Org", kind="business")
    session.add(o)
    session.commit()
    return o


def _service(session: Session, settings: Settings) -> AuthService:
    return AuthService(session, settings)


def test_register_creates_user_and_credentials(
    session: Session, settings: Settings, org: Organisation
) -> None:
    service = _service(session, settings)
    user = service.register(
        org_id=org.id, email="Jane@Example.com", display_name="Jane", password="password123"
    )
    session.commit()

    assert user.email == "jane@example.com"  # normalised
    cred = session.scalar(select(UserCredential).where(UserCredential.user_id == user.id))
    assert cred is not None
    assert cred.password_hash.startswith("$argon2")


def test_register_rejects_duplicate_email(
    session: Session, settings: Settings, org: Organisation
) -> None:
    service = _service(session, settings)
    service.register(org_id=org.id, email="dup@example.com", display_name="A", password="password123")
    session.commit()
    with pytest.raises(DuplicateEmailError):
        service.register(
            org_id=org.id, email="dup@example.com", display_name="B", password="password123"
        )


def test_login_succeeds_with_correct_password(
    session: Session, settings: Settings, org: Organisation
) -> None:
    service = _service(session, settings)
    service.register(org_id=org.id, email="u@example.com", display_name="U", password="password123")
    session.commit()

    pair = service.login(email="u@example.com", password="password123")
    assert pair.access_token
    assert pair.refresh_token
    assert pair.expires_in == settings.access_token_ttl_seconds


def test_login_fails_with_wrong_password(
    session: Session, settings: Settings, org: Organisation
) -> None:
    service = _service(session, settings)
    service.register(org_id=org.id, email="u@example.com", display_name="U", password="password123")
    session.commit()
    with pytest.raises(InvalidCredentialsError):
        service.login(email="u@example.com", password="wrong-password")


def test_login_unknown_user_is_invalid_credentials(
    session: Session, settings: Settings
) -> None:
    service = _service(session, settings)
    with pytest.raises(InvalidCredentialsError):
        service.login(email="nobody@example.com", password="whatever-pw")


def test_account_locks_after_max_failures(
    session: Session, settings: Settings, org: Organisation
) -> None:
    service = _service(session, settings)
    service.register(org_id=org.id, email="u@example.com", display_name="U", password="password123")
    session.commit()

    for _ in range(settings.max_failed_logins):
        with pytest.raises(InvalidCredentialsError):
            service.login(email="u@example.com", password="wrong")

    # Even the correct password is now refused while locked.
    with pytest.raises(AccountLockedError):
        service.login(email="u@example.com", password="password123")


def test_lockout_expires(session: Session, settings: Settings, org: Organisation) -> None:
    service = _service(session, settings)
    service.register(org_id=org.id, email="u@example.com", display_name="U", password="password123")
    session.commit()

    now = dt.datetime.now(tz=dt.UTC)
    for _ in range(settings.max_failed_logins):
        with pytest.raises(InvalidCredentialsError):
            service.login(email="u@example.com", password="wrong", now=now)

    later = now + dt.timedelta(seconds=settings.lockout_seconds + 1)
    pair = service.login(email="u@example.com", password="password123", now=later)
    assert pair.access_token


def test_inactive_account_cannot_login(
    session: Session, settings: Settings, org: Organisation
) -> None:
    service = _service(session, settings)
    user = service.register(
        org_id=org.id, email="u@example.com", display_name="U", password="password123"
    )
    user.status = "suspended"
    session.commit()
    with pytest.raises(AccountInactiveError):
        service.login(email="u@example.com", password="password123")


def test_refresh_rotates_and_revokes_old_token(
    session: Session, settings: Settings, org: Organisation
) -> None:
    service = _service(session, settings)
    service.register(org_id=org.id, email="u@example.com", display_name="U", password="password123")
    session.commit()
    first = service.login(email="u@example.com", password="password123")
    session.commit()

    second = service.refresh(refresh_token=first.refresh_token)
    session.commit()
    assert second.refresh_token != first.refresh_token

    # The original token is now revoked and cannot be reused.
    with pytest.raises(InvalidRefreshTokenError):
        service.refresh(refresh_token=first.refresh_token)


def test_expired_refresh_token_is_rejected(
    session: Session, settings: Settings, org: Organisation
) -> None:
    service = _service(session, settings)
    service.register(org_id=org.id, email="u@example.com", display_name="U", password="password123")
    session.commit()
    now = dt.datetime.now(tz=dt.UTC)
    pair = service.login(email="u@example.com", password="password123", now=now)
    session.commit()

    far_future = now + dt.timedelta(seconds=settings.refresh_token_ttl_seconds + 10)
    with pytest.raises(InvalidRefreshTokenError):
        service.refresh(refresh_token=pair.refresh_token, now=far_future)


def test_logout_revokes_refresh_token(
    session: Session, settings: Settings, org: Organisation
) -> None:
    service = _service(session, settings)
    service.register(org_id=org.id, email="u@example.com", display_name="U", password="password123")
    session.commit()
    pair = service.login(email="u@example.com", password="password123")
    session.commit()

    service.logout(refresh_token=pair.refresh_token)
    session.commit()
    with pytest.raises(InvalidRefreshTokenError):
        service.refresh(refresh_token=pair.refresh_token)


def test_refresh_token_stored_only_as_hash(
    session: Session, settings: Settings, org: Organisation
) -> None:
    service = _service(session, settings)
    service.register(org_id=org.id, email="u@example.com", display_name="U", password="password123")
    session.commit()
    pair = service.login(email="u@example.com", password="password123")
    session.commit()

    rows = session.scalars(select(RefreshToken)).all()
    assert len(rows) == 1
    # The raw token value must never be stored.
    assert rows[0].token_hash != pair.refresh_token
    assert len(rows[0].token_hash) == 64


def test_register_rejects_unknown_organisation(session: Session, settings: Settings) -> None:
    service = _service(session, settings)
    with pytest.raises(UnknownOrganisationError):
        service.register(
            org_id=uuid.uuid4(),
            email="u@example.com",
            display_name="U",
            password="password123",
        )


def test_login_reports_mfa_required_flag(
    session: Session, settings: Settings, org: Organisation
) -> None:
    service = _service(session, settings)
    user = service.register(
        org_id=org.id, email="u@example.com", display_name="U", password="password123"
    )
    session.commit()

    # Default: MFA not enabled, flag is False.
    assert service.login(email="u@example.com", password="password123").mfa_required is False

    # When flagged, the login result reports it (challenge lands in F-08).
    user.mfa_enabled = True
    session.commit()
    assert service.login(email="u@example.com", password="password123").mfa_required is True


def test_prune_removes_expired_and_revoked_tokens(
    session: Session, settings: Settings, org: Organisation
) -> None:
    service = _service(session, settings)
    service.register(org_id=org.id, email="u@example.com", display_name="U", password="password123")
    session.commit()

    now = dt.datetime.now(tz=dt.UTC)
    active = service.login(email="u@example.com", password="password123", now=now)
    expired = service.login(email="u@example.com", password="password123", now=now)
    session.commit()

    # Revoke one (via logout) and let another expire.
    service.logout(refresh_token=expired.refresh_token)
    session.commit()

    far_future = now + dt.timedelta(seconds=settings.refresh_token_ttl_seconds + 1)
    deleted = service.prune_refresh_tokens(now=far_future)
    session.commit()

    # Both tokens are gone after pruning beyond their expiry.
    assert deleted == 2
    assert session.scalars(select(RefreshToken)).all() == []
    # The previously-active token is no longer usable either (it was pruned).
    with pytest.raises(InvalidRefreshTokenError):
        service.refresh(refresh_token=active.refresh_token, now=far_future)


def test_prune_keeps_valid_tokens(
    session: Session, settings: Settings, org: Organisation
) -> None:
    service = _service(session, settings)
    service.register(org_id=org.id, email="u@example.com", display_name="U", password="password123")
    session.commit()
    now = dt.datetime.now(tz=dt.UTC)
    service.login(email="u@example.com", password="password123", now=now)
    session.commit()

    deleted = service.prune_refresh_tokens(now=now)
    assert deleted == 0
    assert len(session.scalars(select(RefreshToken)).all()) == 1
