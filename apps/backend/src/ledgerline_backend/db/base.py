"""Declarative base, portable column types, and audit-ready model mixins.

The mixins encode three cross-cutting concerns every syncable entity needs:
  * a time-ordered UUIDv7 primary key (offline-mintable, collision-free);
  * ``created_at`` / ``updated_at`` audit timestamps;
  * sync bookkeeping columns (``version`` for optimistic concurrency / conflict
    detection, and a soft-delete tombstone) so the same model definitions can
    back both the PostgreSQL server schema and the local SQLite mirror.

No accounting/transaction logic lives here — these are structural foundations.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import DateTime, func
from sqlalchemy.dialects.postgresql import UUID as PgUUID  # noqa: N811 — type alias
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import CHAR, TypeDecorator, TypeEngine

from ledgerline_backend.db.ids import uuid7


class GUID(TypeDecorator[uuid.UUID]):
    """Platform-independent UUID type.

    Uses PostgreSQL's native ``UUID`` where available and falls back to
    ``CHAR(36)`` on SQLite, so identical models work on the server and the local
    desktop database. Values are always Python :class:`uuid.UUID` in the ORM.
    """

    impl = CHAR
    cache_ok = True

    def load_dialect_impl(self, dialect: Dialect) -> TypeEngine[Any]:
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PgUUID(as_uuid=True))
        return dialect.type_descriptor(CHAR(36))

    def process_bind_param(self, value: uuid.UUID | str | None, dialect: Dialect) -> str | None:
        if value is None:
            return None
        if isinstance(value, uuid.UUID):
            return str(value)
        return str(uuid.UUID(value))

    def process_result_value(
        self, value: str | uuid.UUID | None, dialect: Dialect
    ) -> uuid.UUID | None:
        if value is None:
            return None
        if isinstance(value, uuid.UUID):
            return value
        return uuid.UUID(value)


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


class UUIDPrimaryKeyMixin:
    """Adds a time-ordered UUIDv7 primary key, generated application-side."""

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid7)


class TimestampMixin:
    """Adds ``created_at`` / ``updated_at`` columns maintained by the database."""

    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class SyncMixin:
    """Adds sync bookkeeping columns shared by every syncable entity.

    ``version`` increments on each logical change and drives optimistic
    concurrency + sync conflict detection. ``is_deleted`` is a soft-delete
    tombstone so deletions can propagate through the event log rather than
    vanishing (which would break audit and sync).
    """

    version: Mapped[int] = mapped_column(nullable=False, default=1, server_default="1")
    is_deleted: Mapped[bool] = mapped_column(nullable=False, default=False, server_default="false")


class AuditableBase(Base, UUIDPrimaryKeyMixin, TimestampMixin, SyncMixin):
    """Convenience base combining UUID PK, timestamps, and sync columns."""

    __abstract__ = True
