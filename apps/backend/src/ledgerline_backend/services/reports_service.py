"""Reporting service — trial balance, P&L, and balance sheet (AC-09).

Builds engine objects from the company's POSTED journals and runs the engine's
report functions so the reported numbers are computed by the canonical core, not
re-derived in the backend.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from ledgerline_engine.api import (
    Account,
    AccountType,
    Money,
    Posting,
    PostingLine,
    balance_sheet,
    profit_and_loss,
    trial_balance,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from ledgerline_backend.models import ChartOfAccount, Journal, JournalLine

_ENGINE_TYPE = {
    "asset": AccountType.ASSET,
    "liability": AccountType.LIABILITY,
    "equity": AccountType.EQUITY,
    "income": AccountType.INCOME,
    "expense": AccountType.EXPENSE,
}


@dataclass(frozen=True)
class TrialBalanceRowView:
    account_code: str
    account_name: str
    debit_minor: int
    credit_minor: int


@dataclass(frozen=True)
class ReportLineView:
    account_code: str
    account_name: str
    amount_minor: int


@dataclass(frozen=True)
class ProfitAndLossView:
    income: list[ReportLineView] = field(default_factory=list)
    expenses: list[ReportLineView] = field(default_factory=list)
    total_income_minor: int = 0
    total_expenses_minor: int = 0
    net_profit_minor: int = 0


@dataclass(frozen=True)
class BalanceSheetView:
    assets: list[ReportLineView] = field(default_factory=list)
    liabilities: list[ReportLineView] = field(default_factory=list)
    equity: list[ReportLineView] = field(default_factory=list)
    total_assets_minor: int = 0
    total_liabilities_minor: int = 0
    total_equity_minor: int = 0
    retained_earnings_minor: int = 0


class ReportsService:
    """Engine-backed reports for a company."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def _build(
        self, company_id: uuid.UUID, base_currency: str
    ) -> tuple[list[Account], list[Posting]]:
        """Build engine accounts + postings from the company's posted journals."""
        accounts = self._session.scalars(
            select(ChartOfAccount).where(ChartOfAccount.company_id == company_id)
        ).all()
        engine_accounts = {
            a.id: Account(
                code=a.code,
                name=a.name,
                account_type=_ENGINE_TYPE[a.account_type],
                is_active=a.is_active,
            )
            for a in accounts
        }

        posted = self._session.scalars(
            select(Journal).where(
                Journal.company_id == company_id, Journal.is_posted.is_(True)
            )
        ).all()

        postings: list[Posting] = []
        for journal in posted:
            lines = self._session.scalars(
                select(JournalLine)
                .where(JournalLine.journal_id == journal.id)
                .order_by(JournalLine.line_no)
            ).all()
            engine_lines = []
            for ln in lines:
                is_debit = ln.debit_minor > 0
                minor = ln.debit_minor if is_debit else ln.credit_minor
                money = Money(minor, journal.currency)
                engine_lines.append(
                    PostingLine(
                        account=engine_accounts[ln.account_id],
                        amount=money,
                        base_amount=Money(
                            ln.base_debit_minor if is_debit else ln.base_credit_minor,
                            base_currency,
                        ),
                        is_debit=is_debit,
                    )
                )
            if engine_lines:
                postings.append(Posting.of(engine_lines, base_currency=base_currency))
        return list(engine_accounts.values()), postings

    def trial_balance(
        self, company_id: uuid.UUID, *, base_currency: str = "GBP"
    ) -> list[TrialBalanceRowView]:
        """Compute the trial balance over POSTED journals, via the engine."""
        accounts, postings = self._build(company_id, base_currency)
        rows = trial_balance(accounts, postings, base_currency=base_currency)
        return [
            TrialBalanceRowView(
                account_code=r.account.code,
                account_name=r.account.name,
                debit_minor=r.debit.minor_units,
                credit_minor=r.credit.minor_units,
            )
            for r in rows
        ]

    def profit_and_loss(
        self, company_id: uuid.UUID, *, base_currency: str = "GBP"
    ) -> ProfitAndLossView:
        """Compute the P&L over POSTED journals, via the engine."""
        accounts, postings = self._build(company_id, base_currency)
        pnl = profit_and_loss(accounts, postings, base_currency=base_currency)
        return ProfitAndLossView(
            income=[
                ReportLineView(line.account.code, line.account.name, line.amount.minor_units)
                for line in pnl.income
            ],
            expenses=[
                ReportLineView(line.account.code, line.account.name, line.amount.minor_units)
                for line in pnl.expenses
            ],
            total_income_minor=pnl.total_income.minor_units if pnl.total_income else 0,
            total_expenses_minor=pnl.total_expenses.minor_units if pnl.total_expenses else 0,
            net_profit_minor=pnl.net_profit.minor_units if pnl.net_profit else 0,
        )

    def balance_sheet(
        self, company_id: uuid.UUID, *, base_currency: str = "GBP"
    ) -> BalanceSheetView:
        """Compute the balance sheet over POSTED journals, via the engine."""
        accounts, postings = self._build(company_id, base_currency)
        bs = balance_sheet(accounts, postings, base_currency=base_currency)
        return BalanceSheetView(
            assets=[
                ReportLineView(line.account.code, line.account.name, line.amount.minor_units)
                for line in bs.assets
            ],
            liabilities=[
                ReportLineView(line.account.code, line.account.name, line.amount.minor_units)
                for line in bs.liabilities
            ],
            equity=[
                ReportLineView(line.account.code, line.account.name, line.amount.minor_units)
                for line in bs.equity
            ],
            total_assets_minor=bs.total_assets.minor_units if bs.total_assets else 0,
            total_liabilities_minor=bs.total_liabilities.minor_units if bs.total_liabilities else 0,
            total_equity_minor=bs.total_equity.minor_units if bs.total_equity else 0,
            retained_earnings_minor=bs.retained_earnings.minor_units if bs.retained_earnings else 0,
        )
