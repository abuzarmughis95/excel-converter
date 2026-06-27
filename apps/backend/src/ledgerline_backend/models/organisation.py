"""Organisation model.

An organisation is the top-level tenant owner: either a business keeping its own
books or an accounting firm acting for many client companies.
"""

from __future__ import annotations

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from ledgerline_backend.db.base import AuditableBase


class Organisation(AuditableBase):
    """A tenant owner (business or accounting firm)."""

    __tablename__ = "organisations"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # 'business' | 'accounting_firm' — kept as a constrained string at the DB
    # level via a check constraint added in the migration.
    kind: Mapped[str] = mapped_column(String(32), nullable=False, default="business")
