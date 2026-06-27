"""Device registration and lifecycle service.

Handles registering a client device, allocating its globally-unique HLC
``node_id``, and revocation. Node-id allocation is race-safe: the counter row is
locked (``FOR UPDATE`` on PostgreSQL) before being incremented, so two concurrent
registrations can never receive the same id. The server reserves ``node_id = 0``,
so the first device allocated is 1.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from ledgerline_backend.config import Settings
from ledgerline_backend.models import AllocationCounter, Device
from ledgerline_backend.models.allocation import NODE_ID_COUNTER
from ledgerline_backend.util.time import utcnow

# The server itself owns node 0; devices are allocated from 1 upward.
SERVER_NODE_ID = 0


class DeviceError(Exception):
    """Base class for device-related failures."""


class DeviceNotFoundError(DeviceError):
    """The referenced device does not exist."""


class DeviceRevokedError(DeviceError):
    """The device has been revoked and cannot be used."""


class DeviceEntitlementExpiredError(DeviceError):
    """The device's offline entitlement has lapsed and must be renewed."""


@dataclass(frozen=True)
class RegisteredDevice:
    """Result of registering a device."""

    device_id: uuid.UUID
    node_id: int
    entitlement_exp: dt.datetime


# Backwards-compatible alias for the shared helper.
_utcnow = utcnow


def _as_utc(value: dt.datetime) -> dt.datetime:
    """Coerce a possibly-naive datetime (as SQLite returns) to UTC-aware so
    comparisons against an aware ``now`` are valid."""
    return value.replace(tzinfo=dt.UTC) if value.tzinfo is None else value


class DeviceService:
    """Device registration and lifecycle, bound to a session and settings."""

    def __init__(self, session: Session, settings: Settings) -> None:
        self._session = session
        self._settings = settings

    def _allocate_node_id(self) -> int:
        """Atomically allocate the next HLC node id (>= 1).

        Locks the counter row before incrementing so concurrent callers serialise
        and never receive a duplicate. The counter is created on first use.
        """
        dialect = self._session.get_bind().dialect.name
        counter = self._session.get(
            AllocationCounter,
            NODE_ID_COUNTER,
            with_for_update=True if dialect == "postgresql" else False,
        )
        if counter is None:
            # Seed the counter at SERVER_NODE_ID so the first device gets +1.
            counter = AllocationCounter(name=NODE_ID_COUNTER, value=SERVER_NODE_ID)
            self._session.add(counter)
            self._session.flush()

        counter.value += 1
        self._session.flush()
        return counter.value

    def register(
        self,
        *,
        user_id: uuid.UUID,
        name: str,
        platform: str,
        public_key: bytes,
        now: dt.datetime | None = None,
    ) -> RegisteredDevice:
        """Register a new device for a user and assign its node id."""
        moment = now or _utcnow()
        node_id = self._allocate_node_id()
        entitlement_exp = moment + dt.timedelta(
            seconds=self._settings.device_entitlement_ttl_seconds
        )
        device = Device(
            user_id=user_id,
            node_id=node_id,
            name=name,
            platform=platform,
            public_key=public_key,
            entitlement_exp=entitlement_exp,
            last_seen_seq=0,
            revoked=False,
        )
        self._session.add(device)
        self._session.flush()
        return RegisteredDevice(
            device_id=device.id, node_id=node_id, entitlement_exp=entitlement_exp
        )

    def get_active_device(self, device_id: uuid.UUID, *, now: dt.datetime | None = None) -> Device:
        """Return a device that exists, is not revoked, and is still entitled.

        Raises on a missing, revoked, or entitlement-expired device.
        """
        moment = now or _utcnow()
        device = self._session.get(Device, device_id)
        if device is None:
            raise DeviceNotFoundError
        if device.revoked:
            raise DeviceRevokedError
        if _as_utc(device.entitlement_exp) <= moment:
            raise DeviceEntitlementExpiredError
        return device

    def get_owned_device(self, device_id: uuid.UUID, user_id: uuid.UUID) -> Device:
        """Return a device owned by ``user_id`` regardless of revoked/expiry state.

        Used by management actions (e.g. revoke) that must work even on an
        expired or already-revoked device. Treats a device owned by another user
        as not found, to avoid leaking existence.
        """
        device = self._session.get(Device, device_id)
        if device is None or device.user_id != user_id:
            raise DeviceNotFoundError
        return device

    def revoke(self, device_id: uuid.UUID) -> None:
        """Revoke a device so it can no longer participate in sync."""
        device = self._session.get(Device, device_id)
        if device is None:
            raise DeviceNotFoundError
        device.revoked = True

    def list_for_user(self, user_id: uuid.UUID) -> list[Device]:
        """Return all devices registered to a user, newest first."""
        stmt = (
            select(Device)
            .where(Device.user_id == user_id)
            .order_by(Device.created_at.desc())
        )
        return list(self._session.scalars(stmt).all())
