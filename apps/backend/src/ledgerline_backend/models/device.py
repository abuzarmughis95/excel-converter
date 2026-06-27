"""Device model.

A device is a registered client installation (typically the desktop app) that
participates in offline sync. Each device is assigned a globally-unique
``node_id`` used as the node component of the Hybrid Logical Clock, so events
minted on different devices order deterministically and never collide. The
server reserves ``node_id = 0`` for itself; devices receive 1, 2, 3, …

The device's public key is stored so the server can later verify signatures on
the sync events the device pushes. ``entitlement_exp`` bounds how long the device
may operate offline before it must re-check its licence; ``revoked`` lets an
operator disable a lost or compromised device.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, LargeBinary, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ledgerline_backend.db.base import AuditableBase


class Device(AuditableBase):
    """A registered client device participating in sync."""

    __tablename__ = "devices"
    __table_args__ = (UniqueConstraint("node_id", name="uq_device_node_id"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Globally-unique HLC node id (server reserves 0; devices get >= 1).
    node_id: Mapped[int] = mapped_column(Integer, nullable=False)
    # Human-friendly name and platform for display/audit.
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    platform: Mapped[str] = mapped_column(String(16), nullable=False)
    # Device public key (DER/raw bytes) for verifying pushed-event signatures.
    public_key: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    # Offline entitlement / licence expiry.
    entitlement_exp: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Highest server_seq this device has acknowledged on pull (sync bookkeeping).
    last_seen_seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    revoked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
