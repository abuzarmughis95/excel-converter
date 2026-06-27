"""Company membership model.

Associates a user with a company and the role they hold there. This is the
per-company RBAC grant: a user can only see and act on companies they are a
member of, and their role bounds what they may do. One row per (user, company).

Roles:
  * owner       — full control, including managing members and company settings;
  * accountant  — full bookkeeping + compliance, no member management;
  * bookkeeper  — day-to-day bookkeeping;
  * readonly    — view only.
"""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ledgerline_backend.db.base import AuditableBase

# Role ordering by privilege, used for "at least this role" checks.
ROLE_OWNER = "owner"
ROLE_ACCOUNTANT = "accountant"
ROLE_BOOKKEEPER = "bookkeeper"
ROLE_READONLY = "readonly"

ALL_ROLES = (ROLE_OWNER, ROLE_ACCOUNTANT, ROLE_BOOKKEEPER, ROLE_READONLY)

# Higher number = more privilege.
_ROLE_RANK = {ROLE_READONLY: 0, ROLE_BOOKKEEPER: 1, ROLE_ACCOUNTANT: 2, ROLE_OWNER: 3}


def role_at_least(held: str, required: str) -> bool:
    """Whether ``held`` confers at least the privilege of ``required``."""
    return _ROLE_RANK.get(held, -1) >= _ROLE_RANK.get(required, 99)


class CompanyMembership(AuditableBase):
    """A user's membership of, and role within, a company."""

    __tablename__ = "company_memberships"
    __table_args__ = (
        UniqueConstraint("user_id", "company_id", name="uq_membership_user_company"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
