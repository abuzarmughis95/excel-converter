"""Sync event model — the append-only event log.

Every domain write is recorded as an immutable event. The relational projection
tables (companies, chart_of_accounts, …) are derived from this log. ``server_seq``
is the monotonic global ordering assigned by the server on acceptance; it is null
for an event that has only been recorded locally and not yet pushed.

This is structure only: HLC mechanics, hashing, signing, and the apply/projection
logic arrive in Phase 3. Here we define where events live and how they are keyed.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from ledgerline_backend.db.base import Base, UUIDPrimaryKeyMixin


class SyncEvent(Base, UUIDPrimaryKeyMixin):
    """One immutable event in a company's append-only stream."""

    __tablename__ = "sync_events"
    __table_args__ = (
        # The monotonic global sequence is unique once assigned by the server.
        UniqueConstraint("server_seq", name="uq_sync_event_server_seq"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    # Server-assigned monotonic ordering; null until accepted on push.
    server_seq: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    aggregate_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    aggregate_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    event_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)

    # Hybrid Logical Clock components (mechanics implemented in Phase 3).
    hlc_wall: Mapped[int] = mapped_column(BigInteger, nullable=False)
    hlc_counter: Mapped[int] = mapped_column(Integer, nullable=False)
    node_id: Mapped[int] = mapped_column(Integer, nullable=False)

    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=True,
    )
    correlation_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True, index=True)
    causation_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)

    # Per-aggregate hash chain for tamper evidence.
    prev_hash: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    this_hash: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)

    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
