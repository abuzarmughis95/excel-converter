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

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from ledgerline_backend.db.base import AuditableBase


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
