"""User model.

Authentication secrets (password hash, TOTP) are intentionally NOT stored here;
they belong in a separate credentials table introduced with the auth tickets
(F-07/F-08) to limit blast radius. This model carries identity only.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from ledgerline_backend.db.base import AuditableBase


class User(AuditableBase):
    """A person who can authenticate and act within one or more companies."""

    __tablename__ = "users"

    org_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organisations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    # 'active' | 'invited' | 'suspended' | 'disabled' — constrained in migration.
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="invited")
    # Whether this account requires a second factor at login. The TOTP secret and
    # the verification step are added in F-08; until then this stays False and the
    # login flow records (but does not yet challenge) the requirement.
    mfa_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
