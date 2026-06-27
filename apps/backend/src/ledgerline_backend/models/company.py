"""Company, accounting period, and chart-of-accounts models.

These define the structural skeleton of a set of books. There is deliberately NO
posting, balancing, or transaction logic here — that arrives with the accounting
engine in Phase 2. Constraints that span rows (e.g. non-overlapping periods) are
added in the migration; this module declares the shape and column-level rules.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import Date, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ledgerline_backend.db.base import AuditableBase


class Company(AuditableBase):
    """A set of books owned by an organisation (one legal entity's accounts)."""

    __tablename__ = "companies"

    org_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organisations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    base_currency: Mapped[str] = mapped_column(String(3), nullable=False, default="GBP")
    # 'sole_trader' | 'partnership' | 'ltd' | 'micro' | 'small'
    accounts_type: Mapped[str] = mapped_column(String(32), nullable=False, default="ltd")
    companies_house_no: Mapped[str | None] = mapped_column(String(16), nullable=True)
    vat_registration_no: Mapped[str | None] = mapped_column(String(16), nullable=True)


class AccountingPeriod(AuditableBase):
    """A fiscal period within a company. Lockable to protect posted records."""

    __tablename__ = "accounting_periods"
    __table_args__ = (
        UniqueConstraint("company_id", "fiscal_year", name="uq_period_company_year"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    fiscal_year: Mapped[int] = mapped_column(nullable=False)
    starts_on: Mapped[dt.date] = mapped_column(Date, nullable=False)
    ends_on: Mapped[dt.date] = mapped_column(Date, nullable=False)
    # 'open' | 'soft_closed' | 'locked' — constrained in migration.
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")


class ChartOfAccount(AuditableBase):
    """A nominal account in a company's chart of accounts."""

    __tablename__ = "chart_of_accounts"
    __table_args__ = (
        UniqueConstraint("company_id", "code", name="uq_coa_company_code"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    code: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # 'asset' | 'liability' | 'equity' | 'income' | 'expense'
    account_type: Mapped[str] = mapped_column(String(16), nullable=False)
    # 'DR' | 'CR' — the account's normal balance side.
    normal_balance: Mapped[str] = mapped_column(String(2), nullable=False)
    is_control: Mapped[bool] = mapped_column(nullable=False, default=False)
    # 'bank' | 'debtors' | 'creditors' | 'vat' | None
    control_kind: Mapped[str | None] = mapped_column(String(16), nullable=True)
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True)
