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

from ledgerline_backend.models import ChartOfAccount, Journal, JournalLine

# VAT codes that are EC acquisitions/dispatches (feed boxes 2/8/9).
_EC_CODES = {"EC"}
# VAT codes that represent a taxable supply at all (exempt/zero still report net).
_TAXABLE_CODES = {"SR", "RR", "ZR", "EX", "EC"}


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
