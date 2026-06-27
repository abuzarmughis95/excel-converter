"""Tests for trial-balance computation."""

from __future__ import annotations

import pytest

from ledgerline_engine.account import Account, AccountType
from ledgerline_engine.ledger import (
    LedgerNotBalancedError,
    trial_balance,
)
from ledgerline_engine.money import Money
from ledgerline_engine.posting import Posting, PostingLine

BANK = Account("1200", "Bank", AccountType.ASSET)
SALES = Account("4000", "Sales", AccountType.INCOME)
VAT = Account("2200", "VAT", AccountType.LIABILITY)


def _line(account: Account, minor: int, *, debit: bool) -> PostingLine:
    m = Money(minor, "GBP")
    return PostingLine(account=account, amount=m, base_amount=m, is_debit=debit)


def test_trial_balance_balances() -> None:
    posting = Posting.of(
        [
            _line(BANK, 12000, debit=True),
            _line(SALES, 10000, debit=False),
            _line(VAT, 2000, debit=False),
        ],
        base_currency="GBP",
    )
    rows = trial_balance([BANK, SALES, VAT], [posting], base_currency="GBP")
    by_code = {r.account.code: r for r in rows}
    assert by_code["1200"].debit == Money(12000, "GBP")
    assert by_code["4000"].credit == Money(10000, "GBP")
    assert by_code["2200"].credit == Money(2000, "GBP")
    # Whole TB balances: total debit == total credit.
    total_debit = sum(r.debit.minor_units for r in rows)
    total_credit = sum(r.credit.minor_units for r in rows)
    assert total_debit == total_credit == 12000


def test_net_on_normal_side() -> None:
    posting = Posting.of(
        [_line(BANK, 5000, debit=True), _line(SALES, 5000, debit=False)],
        base_currency="GBP",
    )
    rows = {r.account.code: r for r in trial_balance([BANK, SALES], [posting], base_currency="GBP")}
    # Bank is a debit-normal account: net on normal side is its debit balance.
    assert rows["1200"].net_on_normal_side == Money(5000, "GBP")
    # Sales is credit-normal: net on normal side is its credit balance.
    assert rows["4000"].net_on_normal_side == Money(5000, "GBP")


def test_unknown_account_in_posting_raises() -> None:
    posting = Posting.of(
        [_line(BANK, 100, debit=True), _line(SALES, 100, debit=False)],
        base_currency="GBP",
    )
    # Only declare BANK; SALES is unknown to the trial balance.
    with pytest.raises(LedgerNotBalancedError, match="unknown account"):
        trial_balance([BANK], [posting], base_currency="GBP")


def test_empty_postings_balance_to_zero() -> None:
    rows = trial_balance([BANK, SALES], [], base_currency="GBP")
    assert all(r.debit.is_zero and r.credit.is_zero for r in rows)
