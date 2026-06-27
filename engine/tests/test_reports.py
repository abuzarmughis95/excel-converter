"""Tests for the P&L and Balance Sheet reports."""

from __future__ import annotations

import pytest

from ledgerline_engine.account import Account, AccountType
from ledgerline_engine.money import Money
from ledgerline_engine.posting import Posting, PostingLine
from ledgerline_engine.reports import balance_sheet, profit_and_loss

BANK = Account("1200", "Bank", AccountType.ASSET)
CREDITORS = Account("2100", "Creditors", AccountType.LIABILITY)
CAPITAL = Account("3000", "Capital", AccountType.EQUITY)
SALES = Account("4000", "Sales", AccountType.INCOME)
COSTS = Account("5000", "Costs", AccountType.EXPENSE)

ACCOUNTS = [BANK, CREDITORS, CAPITAL, SALES, COSTS]


def _line(account: Account, minor: int, *, debit: bool) -> PostingLine:
    m = Money(minor, "GBP")
    return PostingLine(account=account, amount=m, base_amount=m, is_debit=debit)


def _post(*lines: PostingLine) -> Posting:
    return Posting.of(list(lines), base_currency="GBP")


def test_profit_and_loss_nets_income_less_expenses() -> None:
    postings = [
        _post(_line(BANK, 100000, debit=True), _line(SALES, 100000, debit=False)),
        _post(_line(COSTS, 30000, debit=True), _line(BANK, 30000, debit=False)),
    ]
    pnl = profit_and_loss(ACCOUNTS, postings, base_currency="GBP")
    assert pnl.total_income == Money(100000, "GBP")
    assert pnl.total_expenses == Money(30000, "GBP")
    assert pnl.net_profit == Money(70000, "GBP")  # profit


def test_profit_and_loss_loss_is_negative() -> None:
    postings = [
        _post(_line(BANK, 10000, debit=True), _line(SALES, 10000, debit=False)),
        _post(_line(COSTS, 25000, debit=True), _line(BANK, 25000, debit=False)),
    ]
    pnl = profit_and_loss(ACCOUNTS, postings, base_currency="GBP")
    assert pnl.net_profit == Money(-15000, "GBP")  # loss


def test_balance_sheet_balances_with_retained_earnings() -> None:
    # Owner injects 50,000 capital; makes a 70,000 profit (sales 100k, costs 30k).
    postings = [
        _post(_line(BANK, 50000, debit=True), _line(CAPITAL, 50000, debit=False)),
        _post(_line(BANK, 100000, debit=True), _line(SALES, 100000, debit=False)),
        _post(_line(COSTS, 30000, debit=True), _line(BANK, 30000, debit=False)),
    ]
    bs = balance_sheet(ACCOUNTS, postings, base_currency="GBP")
    # Bank = 50k + 100k - 30k = 120k.
    assert bs.total_assets == Money(120000, "GBP")
    # Equity = capital 50k + retained earnings (profit) 70k = 120k.
    assert bs.retained_earnings == Money(70000, "GBP")
    assert bs.total_equity == Money(120000, "GBP")
    assert bs.total_liabilities == Money(0, "GBP")
    # The accounting identity holds.
    assert bs.total_assets == bs.total_liabilities.add(bs.total_equity)


def test_balance_sheet_with_liabilities() -> None:
    # Buy 30,000 of stock on credit (asset would be needed; use bank+creditor).
    postings = [
        _post(_line(BANK, 50000, debit=True), _line(CAPITAL, 50000, debit=False)),
        # Incur a cost funded by a creditor (Dr cost, Cr creditor).
        _post(_line(COSTS, 30000, debit=True), _line(CREDITORS, 30000, debit=False)),
    ]
    bs = balance_sheet(ACCOUNTS, postings, base_currency="GBP")
    assert bs.total_assets == Money(50000, "GBP")  # bank
    assert bs.total_liabilities == Money(30000, "GBP")  # creditor
    # Equity = capital 50k + retained earnings (loss -30k) = 20k.
    assert bs.retained_earnings == Money(-30000, "GBP")
    assert bs.total_equity == Money(20000, "GBP")
    assert bs.total_assets == bs.total_liabilities.add(bs.total_equity)


def test_empty_reports() -> None:
    pnl = profit_and_loss(ACCOUNTS, [], base_currency="GBP")
    assert pnl.net_profit == Money(0, "GBP")
    bs = balance_sheet(ACCOUNTS, [], base_currency="GBP")
    assert bs.total_assets == Money(0, "GBP")


def test_public_api_exposes_reports() -> None:
    from ledgerline_engine import api

    pnl = api.profit_and_loss(ACCOUNTS, [], base_currency="GBP")
    assert isinstance(pnl, api.ProfitAndLoss)
    bs = api.balance_sheet(ACCOUNTS, [], base_currency="GBP")
    assert isinstance(bs, api.BalanceSheet)


def test_reports_module_does_not_silently_imbalance() -> None:
    # A normal, balanced set must never raise.
    postings = [_post(_line(BANK, 100, debit=True), _line(SALES, 100, debit=False))]
    try:
        balance_sheet(ACCOUNTS, postings, base_currency="GBP")
    except Exception as exc:
        pytest.fail(f"balance_sheet raised on a balanced set: {exc}")
