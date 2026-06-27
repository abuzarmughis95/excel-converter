"""VAT return submission record.

A finalised VAT return: an immutable snapshot of the 9 boxes for a period, with a
manual submission reference (e.g. the HMRC receipt number entered by the user).
This is the "store + lock" half of MTD — the actual HMRC API call is a later step.
Finalising optionally locks the covering accounting period so the figures cannot
change after submission.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ledgerline_backend.db.base import AuditableBase


class HmrcToken(AuditableBase):
    """A company's stored HMRC OAuth2 token (one current token per company).

    Tokens are sensitive; this row is the connection between a company and its
    authorised HMRC session. Refreshing replaces the row in place.
    """

    __tablename__ = "hmrc_tokens"
    __table_args__ = (UniqueConstraint("company_id", name="uq_hmrc_token_company"),)

    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    access_token: Mapped[str] = mapped_column(String(2048), nullable=False)
    refresh_token: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class VatReturnSubmission(AuditableBase):
    """An immutable snapshot of a finalised VAT return for a period."""

    __tablename__ = "vat_return_submissions"

    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    period_start: Mapped[dt.date] = mapped_column(Date, nullable=False)
    period_end: Mapped[dt.date] = mapped_column(Date, nullable=False)
    # User-entered reference (HMRC receipt / manual filing reference).
    reference: Mapped[str] = mapped_column(String(64), nullable=False)
    finalised_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Snapshot of the 9 boxes at finalisation (integer minor units).
    box1_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    box2_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    box3_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    box4_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    box5_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    box6_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    box7_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    box8_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    box9_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # HMRC MTD submission state.
    # 'not_submitted' | 'submitted' | 'error'.
    hmrc_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="not_submitted", server_default="not_submitted"
    )
    # The HMRC obligation period this return was filed against.
    hmrc_period_key: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # HMRC's acknowledgement of an accepted return.
    hmrc_form_bundle: Mapped[str | None] = mapped_column(String(64), nullable=True)
    hmrc_charge_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    hmrc_receipt_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
