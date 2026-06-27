"""VAT return service — derives the 9-box VAT return from posted journals.

Each journal line that carries a ``vat_code`` is a taxable supply: its NET value
is the line amount and ``vat_minor`` is the VAT. The code determines whether it
is a sale or a purchase and whether it is an EC transaction. The 9 boxes are then
computed by the canonical engine.

VAT codes (MVP set):
  SR  standard-rated sale/purchase   (direction inferred from the account type)
  RR  reduced-rated
  ZR  zero-rated
  EX  exempt
  EC  EC acquisition / dispatch of goods

Direction is taken from the account type: income -> sale, expense/asset ->
purchase. (A dedicated sale/purchase flag can replace this later.)
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass

from ledgerline_engine.api import (
    Money,
    VatDirection,
    VatEntry,
    compute_vat_return,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from ledgerline_backend.models import (
    AccountingPeriod,
    ChartOfAccount,
    Journal,
    JournalLine,
    VatReturnSubmission,
)
from ledgerline_backend.services.audit import record_audit
from ledgerline_backend.util.time import utcnow

# VAT codes that are EC acquisitions/dispatches (feed boxes 2/8/9).
_EC_CODES = {"EC"}
# VAT codes that represent a taxable supply at all (exempt/zero still report net).
_TAXABLE_CODES = {"SR", "RR", "ZR", "EX", "EC"}


# Backwards-compatible alias for the shared helper.
_utcnow = utcnow


class VatError(Exception):
    """Base class for VAT submission failures."""


class VatSubmissionExistsError(VatError):
    """A submission already covers this exact period."""


@dataclass(frozen=True)
class VatReturnView:
    box1_minor: int
    box2_minor: int
    box3_minor: int
    box4_minor: int
    box5_minor: int
    box6_minor: int
    box7_minor: int
    box8_minor: int
    box9_minor: int


@dataclass(frozen=True)
class VatSubmissionView:
    id: uuid.UUID
    period_start: dt.date
    period_end: dt.date
    reference: str
    finalised_at: dt.datetime
    boxes: VatReturnView


class VatService:
    """Engine-backed VAT return for a company."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def vat_return(
        self, company_id: uuid.UUID, *, base_currency: str = "GBP"
    ) -> VatReturnView:
        """Compute the 9-box VAT return over POSTED journals."""
        rows = self._session.execute(
            select(JournalLine, ChartOfAccount)
            .join(Journal, Journal.id == JournalLine.journal_id)
            .join(ChartOfAccount, ChartOfAccount.id == JournalLine.account_id)
            .where(
                Journal.company_id == company_id,
                Journal.is_posted.is_(True),
                JournalLine.vat_code.is_not(None),
            )
        ).all()

        entries: list[VatEntry] = []
        for line, account in rows:
            if line.vat_code not in _TAXABLE_CODES:
                continue
            # NET is the line's own amount (debit or credit, whichever is set).
            net_minor = line.debit_minor or line.credit_minor
            direction = (
                VatDirection.SALE
                if account.account_type == "income"
                else VatDirection.PURCHASE
            )
            entries.append(
                VatEntry(
                    direction=direction,
                    net=Money(net_minor, base_currency),
                    vat=Money(line.vat_minor, base_currency),
                    is_ec=line.vat_code in _EC_CODES,
                )
            )

        result = compute_vat_return(entries, base_currency=base_currency)
        return VatReturnView(
            box1_minor=result.box1_minor,
            box2_minor=result.box2_minor,
            box3_minor=result.box3_minor,
            box4_minor=result.box4_minor,
            box5_minor=result.box5_minor,
            box6_minor=result.box6_minor,
            box7_minor=result.box7_minor,
            box8_minor=result.box8_minor,
            box9_minor=result.box9_minor,
        )

    def _to_submission_view(self, sub: VatReturnSubmission) -> VatSubmissionView:
        return VatSubmissionView(
            id=sub.id,
            period_start=sub.period_start,
            period_end=sub.period_end,
            reference=sub.reference,
            finalised_at=sub.finalised_at,
            boxes=VatReturnView(
                box1_minor=sub.box1_minor,
                box2_minor=sub.box2_minor,
                box3_minor=sub.box3_minor,
                box4_minor=sub.box4_minor,
                box5_minor=sub.box5_minor,
                box6_minor=sub.box6_minor,
                box7_minor=sub.box7_minor,
                box8_minor=sub.box8_minor,
                box9_minor=sub.box9_minor,
            ),
        )

    def list_submissions(self, company_id: uuid.UUID) -> list[VatSubmissionView]:
        rows = self._session.scalars(
            select(VatReturnSubmission)
            .where(VatReturnSubmission.company_id == company_id)
            .order_by(VatReturnSubmission.period_end.desc())
        ).all()
        return [self._to_submission_view(s) for s in rows]

    def finalise(
        self,
        *,
        actor_id: uuid.UUID,
        company_id: uuid.UUID,
        period_start: dt.date,
        period_end: dt.date,
        reference: str,
        lock_period: bool = False,
        base_currency: str = "GBP",
    ) -> VatSubmissionView:
        """Snapshot the current 9-box return for a period and record a submission.

        Optionally locks any accounting period fully inside the date range so the
        snapshotted figures cannot change. The actual HMRC API call is a later
        step; ``reference`` is the manual filing/receipt reference.
        """
        if not reference.strip():
            raise VatError("A submission reference is required")
        if period_end < period_start:
            raise VatError("Period end must not be before its start")
        existing = self._session.scalar(
            select(VatReturnSubmission).where(
                VatReturnSubmission.company_id == company_id,
                VatReturnSubmission.period_start == period_start,
                VatReturnSubmission.period_end == period_end,
            )
        )
        if existing is not None:
            raise VatSubmissionExistsError(
                "A VAT return has already been submitted for this period"
            )

        boxes = self.vat_return(company_id, base_currency=base_currency)
        submission = VatReturnSubmission(
            company_id=company_id,
            period_start=period_start,
            period_end=period_end,
            reference=reference.strip(),
            finalised_at=_utcnow(),
            box1_minor=boxes.box1_minor,
            box2_minor=boxes.box2_minor,
            box3_minor=boxes.box3_minor,
            box4_minor=boxes.box4_minor,
            box5_minor=boxes.box5_minor,
            box6_minor=boxes.box6_minor,
            box7_minor=boxes.box7_minor,
            box8_minor=boxes.box8_minor,
            box9_minor=boxes.box9_minor,
        )
        self._session.add(submission)
        self._session.flush()

        if lock_period:
            # Lock any period whose range is fully covered by the return period.
            periods = self._session.scalars(
                select(AccountingPeriod).where(
                    AccountingPeriod.company_id == company_id,
                    AccountingPeriod.starts_on >= period_start,
                    AccountingPeriod.ends_on <= period_end,
                    AccountingPeriod.status != "locked",
                )
            ).all()
            for period in periods:
                period.status = "locked"

        record_audit(
            self._session,
            entity_type="vat_return_submission",
            entity_id=submission.id,
            action="vat_finalised",
            actor_user_id=actor_id,
            company_id=company_id,
        )
        self._session.flush()
        return self._to_submission_view(submission)
