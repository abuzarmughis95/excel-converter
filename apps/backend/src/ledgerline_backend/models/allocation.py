"""Monotonic allocation counters.

A single-row-per-counter table used to hand out strictly increasing integers
(currently HLC ``node_id`` values) atomically and portably. Allocation uses an
``UPDATE ... SET value = value + 1`` guarded by a row lock, which is race-safe on
PostgreSQL (row-level lock) and correct on SQLite (the write serialises). Using a
table rather than a native sequence keeps allocation identical across the server
(PostgreSQL) and tests (SQLite), and lets allocation participate in the caller's
transaction.
"""

from __future__ import annotations

from sqlalchemy import BigInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from ledgerline_backend.db.base import Base

# Counter name for HLC node ids.
NODE_ID_COUNTER = "hlc_node_id"

# Counter name for audit-log insertion sequence (chain ordering).
AUDIT_SEQ_COUNTER = "audit_seq"


class AllocationCounter(Base):
    """A named monotonic counter. ``value`` holds the last allocated number."""

    __tablename__ = "allocation_counters"

    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
