"""Bank account and imported bank-statement line models.

A bank account is a company's real-world account, linked to a chart-of-accounts
account (its general-ledger 'bank' control account). Imported statement lines are
stored against a bank account; each can later be matched/posted to a journal. A
content hash on each line lets re-imports of the same statement skip duplicates.

Amounts are integer minor units (pence) — never floats — to match the engine.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    ForeignKey,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from ledgerline_backend.db.base import AuditableBase


class BankAccount(AuditableBase):
    """A company's bank account, tied to a GL bank account in the chart."""

    __tablename__ = "bank_accounts"
    __table_args__ = (
        UniqueConstraint("company_id", "name", name="uq_bank_account_company_name"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # The general-ledger account (chart_of_accounts) this bank posts to.
    gl_account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("chart_of_accounts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    account_number: Mapped[str | None] = mapped_column(String(34), nullable=True)
    sort_code: Mapped[str | None] = mapped_column(String(16), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="GBP")


class BankStatementLine(AuditableBase):
    """One imported statement transaction, optionally posted to a journal."""

    __tablename__ = "bank_statement_lines"
    __table_args__ = (
        # A given content hash is unique per bank account (re-import dedupe).
        UniqueConstraint("bank_account_id", "content_hash", name="uq_statement_line_hash"),
    )

    bank_account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("bank_accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    line_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    description: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    # Money leaving the account (debit on the statement) and entering it.
    money_out_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    money_in_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    balance_minor: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # Hash of (date, description, amounts) for dedupe on re-import.
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # Set once the line has been posted to a journal.
    is_posted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    posted_journal_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)


class BankReconciliationMark(AuditableBase):
    """Records that a journal line (hitting the bank GL account) is reconciled.

    Reconciliation is recorded out-of-band rather than mutating the (immutable)
    journal line: one mark per (bank_account, journal_line) means that ledger
    entry has been ticked off against the bank statement.
    """

    __tablename__ = "bank_reconciliation_marks"
    __table_args__ = (
        UniqueConstraint(
            "bank_account_id", "journal_line_id", name="uq_recon_mark_account_line"
        ),
    )

    bank_account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("bank_accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    journal_line_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("journal_lines.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
