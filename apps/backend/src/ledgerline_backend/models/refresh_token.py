"""Refresh-token model.

Refresh tokens are opaque random strings. We persist only a SHA-256 *hash* of
each token (never the token itself) so a database compromise does not yield
usable tokens. Rotation is enforced by marking the prior row revoked when a new
token is issued; a presented token whose row is revoked or expired is rejected.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from ledgerline_backend.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class RefreshToken(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A single issued refresh token (stored as a hash) and its lifecycle."""

    __tablename__ = "refresh_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Hex SHA-256 of the opaque token value.
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # When rotated, points at the token that replaced this one (audit trail).
    replaced_by_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
