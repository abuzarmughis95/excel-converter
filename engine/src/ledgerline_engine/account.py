"""Account domain model (AC-02).

An account has a type (asset/liability/equity/income/expense) which determines
its *normal balance* — the side (debit or credit) on which increases are
recorded. Control accounts (debtors, creditors, VAT, bank) may only be written
via their subledger routes; the posting rules enforce this.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class AccountType(Enum):
    """The five fundamental account types."""

    ASSET = "asset"
    LIABILITY = "liability"
    EQUITY = "equity"
    INCOME = "income"
    EXPENSE = "expense"


class NormalBalance(Enum):
    """The side on which an account's balance normally sits."""

    DEBIT = "DR"
    CREDIT = "CR"


# Assets and expenses increase on the debit side; the rest on the credit side.
_NORMAL_BALANCE: dict[AccountType, NormalBalance] = {
    AccountType.ASSET: NormalBalance.DEBIT,
    AccountType.EXPENSE: NormalBalance.DEBIT,
    AccountType.LIABILITY: NormalBalance.CREDIT,
    AccountType.EQUITY: NormalBalance.CREDIT,
    AccountType.INCOME: NormalBalance.CREDIT,
}


class ControlKind(Enum):
    """Subledger control-account kinds. Only their subledger may post to them."""

    BANK = "bank"
    DEBTORS = "debtors"
    CREDITORS = "creditors"
    VAT = "vat"


def normal_balance_for(account_type: AccountType) -> NormalBalance:
    """Return the normal balance side for an account type."""
    return _NORMAL_BALANCE[account_type]


@dataclass(frozen=True, slots=True)
class Account:
    """A nominal account in the chart of accounts."""

    code: str
    name: str
    account_type: AccountType
    is_active: bool = True
    control_kind: ControlKind | None = None

    def __post_init__(self) -> None:
        if not self.code.strip():
            msg = "Account code must not be empty"
            raise ValueError(msg)

    @property
    def normal_balance(self) -> NormalBalance:
        return normal_balance_for(self.account_type)

    @property
    def is_control(self) -> bool:
        return self.control_kind is not None

    @property
    def is_balance_sheet(self) -> bool:
        return self.account_type in (
            AccountType.ASSET,
            AccountType.LIABILITY,
            AccountType.EQUITY,
        )

    @property
    def is_profit_loss(self) -> bool:
        return self.account_type in (AccountType.INCOME, AccountType.EXPENSE)
