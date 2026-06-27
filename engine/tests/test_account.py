"""Tests for the Account domain model and normal-balance derivation."""

from __future__ import annotations

import dataclasses

import pytest

from ledgerline_engine.account import (
    Account,
    AccountType,
    ControlKind,
    NormalBalance,
    normal_balance_for,
)


@pytest.mark.parametrize(
    ("account_type", "expected"),
    [
        (AccountType.ASSET, NormalBalance.DEBIT),
        (AccountType.EXPENSE, NormalBalance.DEBIT),
        (AccountType.LIABILITY, NormalBalance.CREDIT),
        (AccountType.EQUITY, NormalBalance.CREDIT),
        (AccountType.INCOME, NormalBalance.CREDIT),
    ],
)
def test_normal_balance_derivation(account_type: AccountType, expected: NormalBalance) -> None:
    assert normal_balance_for(account_type) is expected
    assert Account("1", "x", account_type).normal_balance is expected


def test_empty_code_rejected() -> None:
    with pytest.raises(ValueError, match="code"):
        Account("  ", "Bank", AccountType.ASSET)


def test_control_account_flags() -> None:
    bank = Account("1200", "Bank", AccountType.ASSET, control_kind=ControlKind.BANK)
    assert bank.is_control is True
    assert Account("4000", "Sales", AccountType.INCOME).is_control is False


def test_statement_classification() -> None:
    assert Account("1000", "x", AccountType.ASSET).is_balance_sheet
    assert Account("2000", "x", AccountType.LIABILITY).is_balance_sheet
    assert Account("3000", "x", AccountType.EQUITY).is_balance_sheet
    assert Account("4000", "x", AccountType.INCOME).is_profit_loss
    assert Account("5000", "x", AccountType.EXPENSE).is_profit_loss
    assert not Account("4000", "x", AccountType.INCOME).is_balance_sheet


def test_account_is_frozen() -> None:
    a = Account("1000", "Bank", AccountType.ASSET)
    with pytest.raises(dataclasses.FrozenInstanceError):
        a.code = "9999"  # type: ignore[misc]
