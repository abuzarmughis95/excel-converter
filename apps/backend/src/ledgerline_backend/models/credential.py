"""User credential model.

Authentication secrets are deliberately kept in a separate table from the
identity-bearing ``User`` to limit blast radius: a query that joins user profile
data never has to touch the password hash, and the credentials row can be locked
down with tighter access controls. One credential row per user (1:1).

Stores only a password *hash* (Argon2id) — never a plaintext or reversible
secret — plus the failed-attempt counter and lockout timestamp used to throttle
brute-force attempts. TOTP/MFA secrets are added in F-08.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from ledgerline_backend.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class UserCredential(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Authentication secrets and lockout state for a single user."""

    __tablename__ = "user_credentials"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    # Argon2id encoded hash string (includes algorithm + parameters + salt).
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    failed_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_until: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
