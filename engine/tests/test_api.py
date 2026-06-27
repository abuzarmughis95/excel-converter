"""Smoke test for the public engine API surface."""

from __future__ import annotations

from decimal import Decimal

from ledgerline_engine import api


def test_public_api_exports_are_usable() -> None:
    bank = api.Account("1200", "Bank", api.AccountType.ASSET)
    sales = api.Account("4000", "Sales", api.AccountType.INCOME)
    dr = api.PostingLine(
        account=bank,
        amount=api.Money(10000, "GBP"),
        base_amount=api.Money(10000, "GBP"),
        is_debit=True,
    )
    cr = api.PostingLine(
        account=sales,
        amount=api.Money(10000, "GBP"),
        base_amount=api.Money(10000, "GBP"),
        is_debit=False,
    )
    posting = api.Posting.of([dr, cr], base_currency="GBP")
    rows = api.trial_balance([bank, sales], [posting], base_currency="GBP")
    assert {r.account.code for r in rows} == {"1200", "4000"}


def test_public_api_rounding_and_period_exposed() -> None:
    assert api.Money(100, "GBP").percentage(Decimal("0.2"), rounding=api.Rounding.HALF_UP)
    assert api.PeriodStatus.OPEN.value == "open"
    assert api.normal_balance_for(api.AccountType.ASSET) is api.NormalBalance.DEBIT
