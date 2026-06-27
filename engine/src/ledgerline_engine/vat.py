"""UK VAT return computation (the 9 boxes).

A VAT return is derived from transactions that carry a VAT treatment: each
taxable amount has a *net* value and a *VAT* value, and a code that says whether
it is a sale or a purchase (and whether it is an EC transaction). This module
computes the standard 9 boxes from a list of such entries.

  Box 1: VAT due on sales and other outputs (output VAT)
  Box 2: VAT due on acquisitions from EC member states
  Box 3: total VAT due (Box 1 + Box 2)
  Box 4: VAT reclaimed on purchases and other inputs (input VAT)
  Box 5: net VAT to pay HMRC or reclaim (|Box 3 - Box 4|)
  Box 6: total value of sales excluding VAT
  Box 7: total value of purchases excluding VAT
  Box 8: total value of supplies of goods to EC member states (ex VAT)
  Box 9: total value of acquisitions of goods from EC member states (ex VAT)

All amounts are integer minor units. Pure and deterministic.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ledgerline_engine.money import Money, sum_money


class VatDirection(Enum):
    """Whether a VAT entry is on the sales or the purchases side."""

    SALE = "sale"
    PURCHASE = "purchase"


@dataclass(frozen=True)
class VatEntry:
    """One VAT-bearing amount: its net value, VAT value, and treatment.

    ``net`` and ``vat`` are non-negative Money in the base currency. ``is_ec``
    marks EC (acquisition/dispatch) transactions, which also feed boxes 2/8/9.
    """

    direction: VatDirection
    net: Money
    vat: Money
    is_ec: bool = False


@dataclass(frozen=True)
class VatReturn:
    """The 9 computed VAT boxes (all integer minor units)."""

    box1_minor: int
    box2_minor: int
    box3_minor: int
    box4_minor: int
    box5_minor: int
    box6_minor: int
    box7_minor: int
    box8_minor: int
    box9_minor: int


def compute_vat_return(entries: list[VatEntry], *, base_currency: str = "GBP") -> VatReturn:
    """Compute the 9-box VAT return from VAT entries.

    The box relationships are enforced here:
      Box 3 = Box 1 + Box 2
      Box 5 = |Box 3 - Box 4|
    """
    sales = [e for e in entries if e.direction is VatDirection.SALE]
    purchases = [e for e in entries if e.direction is VatDirection.PURCHASE]

    box1 = sum_money([e.vat for e in sales], base_currency)
    box2 = sum_money([e.vat for e in purchases if e.is_ec], base_currency)
    box3 = box1.add(box2)
    box4 = sum_money([e.vat for e in purchases], base_currency)
    box5 = Money(abs(box3.subtract(box4).minor_units), base_currency)
    box6 = sum_money([e.net for e in sales], base_currency)
    box7 = sum_money([e.net for e in purchases], base_currency)
    box8 = sum_money([e.net for e in sales if e.is_ec], base_currency)
    box9 = sum_money([e.net for e in purchases if e.is_ec], base_currency)

    return VatReturn(
        box1_minor=box1.minor_units,
        box2_minor=box2.minor_units,
        box3_minor=box3.minor_units,
        box4_minor=box4.minor_units,
        box5_minor=box5.minor_units,
        box6_minor=box6.minor_units,
        box7_minor=box7.minor_units,
        box8_minor=box8.minor_units,
        box9_minor=box9.minor_units,
    )
