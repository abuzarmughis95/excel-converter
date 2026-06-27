"""Journal and journal-line models.

A journal is one double-entry transaction (header). Its lines are the legs
(debit XOR credit against an account). Amounts are stored as integer minor units
(pence) to match the accounting engine — never floats. A journal is created as a
draft and becomes immutable once posted; posting is validated by the engine so
an unbalanced journal can never be persisted in a posted state.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from ledgerline_backend.db.base import AuditableBase


class Journal(AuditableBase):
    """A double-entry transaction header."""

    __tablename__ = "journals"

    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    period_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("accounting_periods.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    journal_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    # 'journal' | 'bank_receipt' | 'bank_payment' | 'reversal' | ...
    journal_type: Mapped[str] = mapped_column(String(32), nullable=False, default="journal")
    reference: Mapped[str | None] = mapped_column(String(64), nullable=True)
    narrative: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="GBP")

    is_posted: Mapped[bool] = mapped_column(nullable=False, default=False, index=True)
    posted_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    posted_by: Mapped[uuid.UUID | None] = mapped_column(nullable=True)

    # Reversal linkage (a reversing journal points at the one it reverses).
    reverses_journal_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    reversed_by_journal_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)


class JournalLine(AuditableBase):
    """One leg of a journal: a debit XOR a credit against an account."""

    __tablename__ = "journal_lines"
    __table_args__ = (
        UniqueConstraint("journal_id", "line_no", name="uq_journal_line_no"),
    )

    journal_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("journals.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("chart_of_accounts.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    # Amounts in integer minor units (pence). One of debit/credit is zero.
    debit_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    credit_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    # Base-currency equivalents (equal to the above when no FX).
    base_debit_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    base_credit_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    narrative: Mapped[str | None] = mapped_column(String(512), nullable=True)
