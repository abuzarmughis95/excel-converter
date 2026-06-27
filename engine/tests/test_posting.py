"""Tests for the Posting value object — the balance invariant.

The defining property: a Posting can be constructed IF AND ONLY IF it balances.
This is proven both by example and by Hypothesis property tests.
"""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from ledgerline_engine.account import Account, AccountType
from ledgerline_engine.money import Money
from ledgerline_engine.posting import (
    EmptyPostingError,
    InvalidLineError,
    Posting,
    PostingLine,
    UnbalancedPostingError,
)

BANK = Account("1200", "Bank", AccountType.ASSET)
SALES = Account("4000", "Sales", AccountType.INCOME)
EXPENSE = Account("5000", "Expense", AccountType.EXPENSE)
INACTIVE = Account("9999", "Old", AccountType.EXPENSE, is_active=False)


def _line(account: Account, minor: int, *, debit: bool) -> PostingLine:
    money = Money(minor, "GBP")
    return PostingLine(account=account, amount=money, base_amount=money, is_debit=debit)


def test_balanced_posting_constructs() -> None:
    posting = Posting.of(
        [_line(BANK, 10000, debit=True), _line(SALES, 10000, debit=False)],
        base_currency="GBP",
    )
    assert posting.total_debit == Money(10000, "GBP")
    assert posting.total_credit == Money(10000, "GBP")


def test_unbalanced_posting_raises() -> None:
    with pytest.raises(UnbalancedPostingError):
        Posting.of(
            [_line(BANK, 10000, debit=True), _line(SALES, 9999, debit=False)],
            base_currency="GBP",
        )


def test_multi_line_balanced_posting() -> None:
    # Dr Bank 120, Cr Sales 100, Cr VAT 20.
    vat = Account("2200", "VAT", AccountType.LIABILITY)
    posting = Posting.of(
        [
            _line(BANK, 12000, debit=True),
            _line(SALES, 10000, debit=False),
            _line(vat, 2000, debit=False),
        ],
        base_currency="GBP",
    )
    assert posting.total_debit == Money(12000, "GBP")


def test_posting_needs_at_least_two_lines() -> None:
    with pytest.raises(EmptyPostingError):
        Posting.of([_line(BANK, 10000, debit=True)], base_currency="GBP")


def test_posting_of_empty_list_raises() -> None:
    with pytest.raises(EmptyPostingError):
        Posting.of([], base_currency="GBP")


def test_posting_needs_a_debit_and_a_credit() -> None:
    with pytest.raises(UnbalancedPostingError):
        Posting.of(
            [_line(BANK, 5000, debit=True), _line(SALES, 5000, debit=True)],
            base_currency="GBP",
        )


def test_line_rejects_zero_amount() -> None:
    with pytest.raises(InvalidLineError):
        _line(BANK, 0, debit=True)


def test_line_rejects_negative_amount() -> None:
    with pytest.raises(InvalidLineError):
        PostingLine(
            account=BANK,
            amount=Money(-100, "GBP"),
            base_amount=Money(-100, "GBP"),
            is_debit=True,
        )


def test_line_rejects_inactive_account() -> None:
    with pytest.raises(InvalidLineError):
        _line(INACTIVE, 100, debit=True)


def test_mixed_transaction_currencies_rejected() -> None:
    usd_line = PostingLine(
        account=BANK, amount=Money(100, "USD"), base_amount=Money(80, "GBP"), is_debit=True
    )
    gbp_line = _line(SALES, 80, debit=False)
    with pytest.raises(InvalidLineError):
        Posting.of([usd_line, gbp_line], base_currency="GBP")


def test_fx_posting_balances_in_both_currencies() -> None:
    # A USD transaction recorded in GBP base: balanced in USD and in GBP.
    dr = PostingLine(
        account=BANK, amount=Money(10000, "USD"), base_amount=Money(8000, "GBP"), is_debit=True
    )
    cr = PostingLine(
        account=SALES, amount=Money(10000, "USD"), base_amount=Money(8000, "GBP"), is_debit=False
    )
    posting = Posting.of([dr, cr], base_currency="GBP")
    assert posting.currency == "USD"
    assert posting.base_currency == "GBP"


def test_fx_unbalanced_in_base_raises() -> None:
    # Balanced in USD but NOT in GBP base — must raise.
    dr = PostingLine(
        account=BANK, amount=Money(10000, "USD"), base_amount=Money(8000, "GBP"), is_debit=True
    )
    cr = PostingLine(
        account=SALES, amount=Money(10000, "USD"), base_amount=Money(7999, "GBP"), is_debit=False
    )
    with pytest.raises(UnbalancedPostingError):
        Posting.of([dr, cr], base_currency="GBP")


# -- property-based: balanced <=> constructable ----------------------------

_amt = st.integers(min_value=1, max_value=10**9)


@given(amount=_amt)
def test_any_equal_two_line_posting_constructs(amount: int) -> None:
    posting = Posting.of(
        [_line(BANK, amount, debit=True), _line(SALES, amount, debit=False)],
        base_currency="GBP",
    )
    assert posting.total_debit == posting.total_credit


@given(debit=_amt, credit=_amt)
def test_unequal_two_line_posting_never_constructs(debit: int, credit: int) -> None:
    if debit == credit:
        return  # equal case is covered above
    with pytest.raises(UnbalancedPostingError):
        Posting.of(
            [_line(BANK, debit, debit=True), _line(SALES, credit, debit=False)],
            base_currency="GBP",
        )


@given(
    splits=st.lists(_amt, min_size=1, max_size=8),
)
def test_split_credits_balance(splits: list[int]) -> None:
    # One debit equal to the sum of N credits always balances.
    total = sum(splits)
    accounts = [Account(f"4{i:03d}", f"Sales{i}", AccountType.INCOME) for i in range(len(splits))]
    lines = [_line(BANK, total, debit=True)]
    lines += [_line(accounts[i], splits[i], debit=False) for i in range(len(splits))]
    posting = Posting.of(lines, base_currency="GBP")
    assert posting.total_debit == Money(total, "GBP")
