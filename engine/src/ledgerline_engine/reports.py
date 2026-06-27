"""Profit & Loss and Balance Sheet reports (pure functions over postings).

Both build on the trial balance. The P&L nets income against expenses to a net
profit/loss for the period. The Balance Sheet groups assets, liabilities, and
equity, and folds the period's net profit into retained earnings so the
fundamental identity holds: Assets == Liabilities + Equity (to the penny).

Pure and deterministic — exercised by the golden vectors.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ledgerline_engine.account import Account, AccountType, NormalBalance
from ledgerline_engine.ledger import TrialBalanceRow, trial_balance
from ledgerline_engine.money import Money, sum_money
from ledgerline_engine.posting import Posting


class ReportNotBalancedError(Exception):
    """The balance sheet does not balance (Assets != Liabilities + Equity)."""


@dataclass(frozen=True)
class ReportLine:
    """One account's signed amount on a report, expressed in the natural sign
    for its statement (income/liability/equity positive when credit-heavy;
    asset/expense positive when debit-heavy)."""

    account: Account
    amount: Money


@dataclass(frozen=True)
class ProfitAndLoss:
    """Income, expenses, and the resulting net profit (positive) or loss."""

    income: list[ReportLine] = field(default_factory=list)
    expenses: list[ReportLine] = field(default_factory=list)
    total_income: Money | None = None
    total_expenses: Money | None = None
    net_profit: Money | None = None


@dataclass(frozen=True)
class BalanceSheet:
    """Assets, liabilities, equity (incl. retained earnings) at a point in time."""

    assets: list[ReportLine] = field(default_factory=list)
    liabilities: list[ReportLine] = field(default_factory=list)
    equity: list[ReportLine] = field(default_factory=list)
    total_assets: Money | None = None
    total_liabilities: Money | None = None
    total_equity: Money | None = None
    retained_earnings: Money | None = None


def _signed_amount(row: TrialBalanceRow) -> Money:
    """Amount on the account's normal side (>= 0 for a normally-behaved account)."""
    if row.account.normal_balance is NormalBalance.DEBIT:
        return row.debit.subtract(row.credit)
    return row.credit.subtract(row.debit)


def profit_and_loss(
    accounts: list[Account], postings: list[Posting], *, base_currency: str
) -> ProfitAndLoss:
    """Compute the P&L (income, expenses, net profit) over the postings."""
    rows = trial_balance(accounts, postings, base_currency=base_currency)
    income: list[ReportLine] = []
    expenses: list[ReportLine] = []
    for row in rows:
        amount = _signed_amount(row)
        if row.account.account_type is AccountType.INCOME:
            income.append(ReportLine(account=row.account, amount=amount))
        elif row.account.account_type is AccountType.EXPENSE:
            expenses.append(ReportLine(account=row.account, amount=amount))

    total_income = sum_money([line.amount for line in income], base_currency)
    total_expenses = sum_money([line.amount for line in expenses], base_currency)
    net_profit = total_income.subtract(total_expenses)
    return ProfitAndLoss(
        income=income,
        expenses=expenses,
        total_income=total_income,
        total_expenses=total_expenses,
        net_profit=net_profit,
    )


def balance_sheet(
    accounts: list[Account], postings: list[Posting], *, base_currency: str
) -> BalanceSheet:
    """Compute the Balance Sheet, folding net profit into retained earnings.

    Raises :class:`ReportNotBalancedError` if Assets != Liabilities + Equity,
    which should be impossible given balanced postings — a defensive check.
    """
    rows = trial_balance(accounts, postings, base_currency=base_currency)
    assets: list[ReportLine] = []
    liabilities: list[ReportLine] = []
    equity: list[ReportLine] = []
    for row in rows:
        amount = _signed_amount(row)
        if row.account.account_type is AccountType.ASSET:
            assets.append(ReportLine(account=row.account, amount=amount))
        elif row.account.account_type is AccountType.LIABILITY:
            liabilities.append(ReportLine(account=row.account, amount=amount))
        elif row.account.account_type is AccountType.EQUITY:
            equity.append(ReportLine(account=row.account, amount=amount))

    # The period's net profit accrues to equity as retained earnings.
    pnl = profit_and_loss(accounts, postings, base_currency=base_currency)
    retained_earnings = pnl.net_profit or Money.zero(base_currency)

    total_assets = sum_money([line.amount for line in assets], base_currency)
    total_liabilities = sum_money([line.amount for line in liabilities], base_currency)
    explicit_equity = sum_money([line.amount for line in equity], base_currency)
    total_equity = explicit_equity.add(retained_earnings)

    if total_assets != total_liabilities.add(total_equity):
        msg = (
            f"Balance sheet does not balance: assets {total_assets} != "
            f"liabilities {total_liabilities} + equity {total_equity}"
        )
        raise ReportNotBalancedError(msg)

    return BalanceSheet(
        assets=assets,
        liabilities=liabilities,
        equity=equity,
        total_assets=total_assets,
        total_liabilities=total_liabilities,
        total_equity=total_equity,
        retained_earnings=retained_earnings,
    )
