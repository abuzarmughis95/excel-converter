"""Audit log model.

An immutable, hash-chained record of every significant action. It is append-only
by policy: rows are never updated or deleted (enforced at the application layer
and, in a later ticket, by database triggers). The ``prev_hash`` / ``this_hash``
chain makes tampering detectable. No soft-delete or version columns — an audit
entry, once written, is final.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import BigInteger, DateTime, ForeignKey, LargeBinary, String, func
from sqlalchemy.orm import Mapped, mapped_column

from ledgerline_backend.db.base import Base, UUIDPrimaryKeyMixin


class AuditLog(Base, UUIDPrimaryKeyMixin):
    """One immutable audit entry: who did what, when, and to which entity."""

    __tablename__ = "audit_logs"

    # Strictly monotonic insertion order — the authoritative chain order, since
    # created_at alone is too coarse to order rapid same-entity writes. Assigned
    # application-side from a race-safe allocation counter (portable across
    # PostgreSQL and SQLite, unlike a native Identity/sequence).
    seq: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True)

    company_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("companies.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    # Optional human reason for sensitive actions (e.g. unpost, period unlock).
    reason: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    # Hash chain for tamper evidence; populated by the audit writer (later ticket).
    prev_hash: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    this_hash: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        index=True,
    )
