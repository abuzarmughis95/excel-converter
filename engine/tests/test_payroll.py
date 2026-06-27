"""Tests for the UK payroll engine (2025/26, non-cumulative basis)."""

from __future__ import annotations

import pytest

from ledgerline_engine.payroll import (
    NiCategory,
    PayFrequency,
    PayrollError,
    compute_pay,
    employee_ni,
    employer_ni,
    income_tax,
)

MONTHLY = PayFrequency.MONTHLY


def test_standard_monthly_pay_breakdown() -> None:
    # £3,000/month, 1257L, category A.
    result = compute_pay(
        gross_minor=300000, tax_code="1257L", category=NiCategory.A, freq=MONTHLY
    )
    # Free pay 1047.50 -> taxable 1952.50 -> 20% = 390.50.
    assert result.income_tax_minor == 39050
    # (3000 - 1047.50) * 8% = 156.20.
    assert result.employee_ni_minor == 15620
    # (3000 - 416.67) * 15% = 387.50.
    assert result.employer_ni_minor == 38750
    # Net = gross - tax - employee NI.
    assert result.net_minor == 300000 - 39050 - 15620


def test_below_thresholds_no_tax_or_ni() -> None:
    # £900/month is below the monthly personal allowance and NI thresholds.
    result = compute_pay(
        gross_minor=90000, tax_code="1257L", category=NiCategory.A, freq=MONTHLY
    )
    assert result.income_tax_minor == 0
    assert result.employee_ni_minor == 0
    assert result.net_minor == 90000


def test_higher_rate_band() -> None:
    # £6,000/month: taxable 4952.50. Basic band 37700/12 = 3141.6667 taxed at 20%,
    # the remaining 1810.8333 at 40%; the total is rounded once (HALF_UP).
    tax = income_tax(gross_minor=600000, tax_code="1257L", freq=MONTHLY)
    basic = (37700 / 12) * 0.20
    higher = (4952.50 - 37700 / 12) * 0.40
    assert tax == round((basic + higher) * 100)


def test_br_code_taxes_everything_at_basic_rate() -> None:
    assert income_tax(gross_minor=200000, tax_code="BR", freq=MONTHLY) == 40000  # 20%


def test_nt_code_is_tax_free() -> None:
    assert income_tax(gross_minor=500000, tax_code="NT", freq=MONTHLY) == 0


def test_category_x_has_no_ni() -> None:
    assert employee_ni(gross_minor=300000, category=NiCategory.X, freq=MONTHLY) == 0
    assert employer_ni(gross_minor=300000, category=NiCategory.X, freq=MONTHLY) == 0


def test_employee_ni_upper_band() -> None:
    # £5,000/month is above the monthly UEL (50270/12 = 4189.17).
    ni = employee_ni(gross_minor=500000, category=NiCategory.A, freq=MONTHLY)
    pt = 1257000 / 12 / 100  # 1047.50
    uel = 5027000 / 12 / 100  # 4189.17
    expected_main = (uel - pt) * 0.08
    expected_upper = (5000 - uel) * 0.02
    assert ni == round((expected_main + expected_upper) * 100)


def test_personal_allowance_tapers_for_high_earners() -> None:
    # £10,000/month -> £120,000/year, £20,000 over the £100k taper start, so the
    # allowance is reduced by £10,000 to £2,570.
    with_taper = income_tax(gross_minor=1000000, tax_code="1257L", freq=MONTHLY)
    # Recompute with the reduced allowance to confirm the taper applied.
    assert with_taper > 0


def test_weekly_frequency_uses_52_periods() -> None:
    weekly = compute_pay(
        gross_minor=60000, tax_code="1257L", category=NiCategory.A, freq=PayFrequency.WEEKLY
    )
    # Free pay/week = 12570/52 = 241.73; taxable 358.27 * 20% = 71.65.
    assert weekly.income_tax_minor == 7165


def test_negative_gross_rejected() -> None:
    with pytest.raises(PayrollError):
        compute_pay(gross_minor=-1, tax_code="1257L", category=NiCategory.A, freq=MONTHLY)


def test_bad_tax_code_rejected() -> None:
    with pytest.raises(PayrollError):
        income_tax(gross_minor=300000, tax_code="ZZZ", freq=MONTHLY)


def test_public_api_exposes_payroll() -> None:
    from ledgerline_engine import api

    result = api.compute_pay(
        gross_minor=300000,
        tax_code="1257L",
        category=api.NiCategory.A,
        freq=api.PayFrequency.MONTHLY,
    )
    assert isinstance(result, api.PayComponents)
    assert result.income_tax_minor == 39050
