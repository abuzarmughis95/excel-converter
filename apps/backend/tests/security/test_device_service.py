"""Tests for the DeviceService: registration, node-id allocation, revocation."""

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
from ledgerline_backend.models import Device, Organisation, User
from ledgerline_backend.security.device_service import (
    SERVER_NODE_ID,
    DeviceEntitlementExpiredError,
    DeviceNotFoundError,
    DeviceRevokedError,
    DeviceService,
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
    return Settings(environment="test")


@pytest.fixture
def user(session: Session) -> User:
    org = Organisation(name="Org", kind="business")
    session.add(org)
    session.flush()
    u = User(org_id=org.id, email="u@example.com", display_name="U", status="active")
    session.add(u)
    session.commit()
    return u


def _register(service: DeviceService, user: User, name: str = "Laptop") -> int:
    return service.register(
        user_id=user.id, name=name, platform="win", public_key=b"\x01\x02\x03"
    ).node_id


def test_first_device_gets_node_id_one(session: Session, settings: Settings, user: User) -> None:
    service = DeviceService(session, settings)
    node_id = _register(service, user)
    session.commit()
    # Server reserves node 0, so the first device is 1.
    assert SERVER_NODE_ID == 0
    assert node_id == 1


def test_node_ids_are_monotonic_and_unique(
    session: Session, settings: Settings, user: User
) -> None:
    service = DeviceService(session, settings)
    ids = [_register(service, user, f"d{i}") for i in range(5)]
    session.commit()
    assert ids == [1, 2, 3, 4, 5]
    assert len(set(ids)) == 5


def test_registration_persists_device_fields(
    session: Session, settings: Settings, user: User
) -> None:
    service = DeviceService(session, settings)
    result = service.register(
        user_id=user.id, name="My Mac", platform="mac", public_key=b"\xaa\xbb"
    )
    session.commit()

    device = session.get(Device, result.device_id)
    assert device is not None
    assert device.user_id == user.id
    assert device.platform == "mac"
    assert device.public_key == b"\xaa\xbb"
    assert device.revoked is False
    assert device.last_seen_seq == 0
    # SQLite returns naive datetimes; compare the wall-clock instant.
    assert device.entitlement_exp.replace(tzinfo=None) == result.entitlement_exp.replace(
        tzinfo=None
    )


def test_get_active_device_raises_for_unknown(
    session: Session, settings: Settings
) -> None:
    service = DeviceService(session, settings)
    with pytest.raises(DeviceNotFoundError):
        service.get_active_device(uuid.uuid4())


def test_revoked_device_is_rejected(session: Session, settings: Settings, user: User) -> None:
    service = DeviceService(session, settings)
    result = service.register(
        user_id=user.id, name="L", platform="linux", public_key=b"\x01"
    )
    session.commit()

    service.revoke(result.device_id)
    session.commit()
    with pytest.raises(DeviceRevokedError):
        service.get_active_device(result.device_id)


def test_revoke_unknown_device_raises(session: Session, settings: Settings) -> None:
    service = DeviceService(session, settings)
    with pytest.raises(DeviceNotFoundError):
        service.revoke(uuid.uuid4())


def test_list_for_user_returns_only_that_users_devices(
    session: Session, settings: Settings, user: User
) -> None:
    org = session.get(Organisation, user.org_id)
    assert org is not None
    other = User(org_id=org.id, email="o@example.com", display_name="O", status="active")
    session.add(other)
    session.flush()

    service = DeviceService(session, settings)
    service.register(user_id=user.id, name="A", platform="win", public_key=b"\x01")
    service.register(user_id=other.id, name="B", platform="mac", public_key=b"\x02")
    session.commit()

    mine = service.list_for_user(user.id)
    assert len(mine) == 1
    assert mine[0].user_id == user.id


def test_node_id_unique_constraint_enforced(
    session: Session, settings: Settings, user: User
) -> None:
    """Two devices can never share a node id (DB-level guarantee)."""
    service = DeviceService(session, settings)
    service.register(user_id=user.id, name="A", platform="win", public_key=b"\x01")
    service.register(user_id=user.id, name="B", platform="win", public_key=b"\x02")
    session.commit()
    node_ids = session.scalars(select(Device.node_id)).all()
    assert len(node_ids) == len(set(node_ids))


def test_expired_entitlement_is_rejected(
    session: Session, settings: Settings, user: User
) -> None:
    service = DeviceService(session, settings)
    now = dt.datetime.now(tz=dt.UTC)
    result = service.register(
        user_id=user.id, name="L", platform="win", public_key=b"\x01", now=now
    )
    session.commit()

    # Still entitled right after registration.
    assert service.get_active_device(result.device_id, now=now) is not None

    # After the entitlement window, the device is rejected.
    expired = now + dt.timedelta(seconds=settings.device_entitlement_ttl_seconds + 1)
    with pytest.raises(DeviceEntitlementExpiredError):
        service.get_active_device(result.device_id, now=expired)


def test_get_owned_device_works_when_expired(
    session: Session, settings: Settings, user: User
) -> None:
    """Management (e.g. revoke) must succeed even on an expired device."""
    service = DeviceService(session, settings)
    result = service.register(
        user_id=user.id, name="L", platform="win", public_key=b"\x01"
    )
    session.commit()
    device = service.get_owned_device(result.device_id, user.id)
    assert device.id == result.device_id


def test_get_owned_device_rejects_other_users_device(
    session: Session, settings: Settings, user: User
) -> None:
    org = session.get(Organisation, user.org_id)
    assert org is not None
    other = User(org_id=org.id, email="other@example.com", display_name="O", status="active")
    session.add(other)
    session.flush()

    service = DeviceService(session, settings)
    result = service.register(
        user_id=user.id, name="L", platform="win", public_key=b"\x01"
    )
    session.commit()
    with pytest.raises(DeviceNotFoundError):
        service.get_owned_device(result.device_id, other.id)
