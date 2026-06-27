"""UK payroll calculation: PAYE income tax and National Insurance.

Computes, for one pay period, an employee's PAYE income tax, employee (Class 1
primary) NI, employer (secondary) NI, and net pay from gross pay, a tax code,
and an NI category.

This is a *non-cumulative* (Week 1 / Month 1 basis) calculation using the
2025/26 thresholds and rates: it taxes each period independently against a per-
period proportion of the annual allowances/bands. It does not perform cumulative
year-to-date reconciliation, Scottish/Welsh variants, student loans, or the many
edge cases of HMRC's exact tables — it is a correct, transparent core for the
common monthly/weekly case. All amounts are integer minor units (pence). Pure
and deterministic.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from enum import Enum

# -- 2025/26 UK thresholds and rates (annual, in minor units / percent) --

# Income tax (rUK).
_PERSONAL_ALLOWANCE = 1257000  # £12,570 (the 1257L code)
_BASIC_RATE_LIMIT = 3770000  # £37,700 of taxable income at basic rate
_BASIC_RATE = Decimal("20")
_HIGHER_RATE = Decimal("40")
_ADDITIONAL_RATE = Decimal("45")
_ADDITIONAL_THRESHOLD = 12504000  # £125,040 taxable income for additional rate
# Personal allowance tapers away above £100,000 (£1 lost per £2 over).
_PA_TAPER_START = 10000000  # £100,000

# National Insurance (annual-equivalent thresholds; per-period derived below).
_NI_PRIMARY_THRESHOLD = 1257000  # £12,570 employee NI starts
_NI_UPPER_EARNINGS = 5027000  # £50,270 upper earnings limit
_NI_SECONDARY_THRESHOLD = 500000  # £5,000 employer NI starts (2025/26)
_NI_EMPLOYEE_MAIN = Decimal("8")  # 8% between PT and UEL
_NI_EMPLOYEE_UPPER = Decimal("2")  # 2% above UEL
_NI_EMPLOYER_RATE = Decimal("15")  # 15% above secondary threshold (2025/26)


class PayFrequency(Enum):
    MONTHLY = "monthly"
    WEEKLY = "weekly"

    @property
    def periods_per_year(self) -> int:
        return 12 if self is PayFrequency.MONTHLY else 52


class NiCategory(Enum):
    """The common NI categories handled here."""

    A = "A"  # standard
    X = "X"  # no NI (e.g. under 16 / over state pension age)


class PayrollError(Exception):
    """Invalid payroll parameters."""


@dataclass(frozen=True)
class PayComponents:
    """The computed breakdown of a single period's pay (minor units)."""

    gross_minor: int
    income_tax_minor: int
    employee_ni_minor: int
    employer_ni_minor: int
    net_minor: int


def _round(value: Decimal) -> int:
    return int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _per_period(annual_minor: int, freq: PayFrequency) -> Decimal:
    return Decimal(annual_minor) / Decimal(freq.periods_per_year)


def _free_pay_annual(tax_code: str) -> int:
    """Annual tax-free allowance from a numeric suffix tax code, e.g. '1257L'.

    'BR' taxes everything at basic rate (no allowance); 'NT' means no tax. The
    numeric portion is the allowance in tens of pounds (HMRC convention).
    """
    code = tax_code.strip().upper()
    if code == "NT":
        return -1  # sentinel: no tax at all
    if code in {"BR", "D0", "D1"}:
        return 0
    digits = "".join(c for c in code if c.isdigit())
    if not digits:
        raise PayrollError(f"Unrecognised tax code {tax_code!r}")
    return int(digits) * 10 * 100  # tens of pounds -> minor units


def income_tax(*, gross_minor: int, tax_code: str, freq: PayFrequency) -> int:
    """PAYE income tax for one period (non-cumulative / Month 1 basis)."""
    free_annual = _free_pay_annual(tax_code)
    if free_annual == -1:  # NT code
        return 0
    code = tax_code.strip().upper()
    if code in {"BR"}:
        return _round(Decimal(gross_minor) * _BASIC_RATE / Decimal(100))
    if code in {"D0"}:
        return _round(Decimal(gross_minor) * _HIGHER_RATE / Decimal(100))
    if code in {"D1"}:
        return _round(Decimal(gross_minor) * _ADDITIONAL_RATE / Decimal(100))

    # Taper the personal allowance for high earners (annualised gross estimate).
    annual_gross = gross_minor * freq.periods_per_year
    if annual_gross > _PA_TAPER_START:
        reduction = (annual_gross - _PA_TAPER_START) // 2
        free_annual = max(0, free_annual - reduction)

    free_period = _per_period(free_annual, freq)
    taxable = Decimal(gross_minor) - free_period
    if taxable <= 0:
        return 0

    basic_band = _per_period(_BASIC_RATE_LIMIT, freq)
    higher_band_top = _per_period(_ADDITIONAL_THRESHOLD, freq)

    tax = Decimal(0)
    # Basic rate.
    basic = min(taxable, basic_band)
    tax += basic * _BASIC_RATE / Decimal(100)
    # Higher rate.
    if taxable > basic_band:
        higher = min(taxable, higher_band_top) - basic_band
        tax += higher * _HIGHER_RATE / Decimal(100)
    # Additional rate.
    if taxable > higher_band_top:
        additional = taxable - higher_band_top
        tax += additional * _ADDITIONAL_RATE / Decimal(100)
    return _round(tax)


def employee_ni(*, gross_minor: int, category: NiCategory, freq: PayFrequency) -> int:
    """Employee (primary Class 1) NI for one period."""
    if category is NiCategory.X:
        return 0
    pt = _per_period(_NI_PRIMARY_THRESHOLD, freq)
    uel = _per_period(_NI_UPPER_EARNINGS, freq)
    gross = Decimal(gross_minor)
    if gross <= pt:
        return 0
    ni = Decimal(0)
    main = min(gross, uel) - pt
    ni += main * _NI_EMPLOYEE_MAIN / Decimal(100)
    if gross > uel:
        ni += (gross - uel) * _NI_EMPLOYEE_UPPER / Decimal(100)
    return _round(ni)


def employer_ni(*, gross_minor: int, category: NiCategory, freq: PayFrequency) -> int:
    """Employer (secondary Class 1) NI for one period."""
    if category is NiCategory.X:
        return 0
    st = _per_period(_NI_SECONDARY_THRESHOLD, freq)
    gross = Decimal(gross_minor)
    if gross <= st:
        return 0
    return _round((gross - st) * _NI_EMPLOYER_RATE / Decimal(100))


def compute_pay(
    *,
    gross_minor: int,
    tax_code: str,
    category: NiCategory,
    freq: PayFrequency,
) -> PayComponents:
    """Full breakdown for one period: tax, employee/employer NI, and net pay."""
    if gross_minor < 0:
        raise PayrollError("Gross pay must be non-negative")
    tax = income_tax(gross_minor=gross_minor, tax_code=tax_code, freq=freq)
    ee_ni = employee_ni(gross_minor=gross_minor, category=category, freq=freq)
    er_ni = employer_ni(gross_minor=gross_minor, category=category, freq=freq)
    net = gross_minor - tax - ee_ni
    return PayComponents(
        gross_minor=gross_minor,
        income_tax_minor=tax,
        employee_ni_minor=ee_ni,
        employer_ni_minor=er_ni,
        net_minor=net,
    )
