"""Reporting service — trial balance over posted journals (AC-09 start).

Builds engine objects from the company's posted journals and runs the engine's
``trial_balance`` so the reported numbers are computed by the canonical core,
not re-derived in the backend.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from ledgerline_engine.api import (
    Account,
    AccountType,
    Money,
    Posting,
    PostingLine,
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


class ReportsService:
    """Engine-backed reports for a company."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def trial_balance(self, company_id: uuid.UUID, *, base_currency: str = "GBP") -> list[
        TrialBalanceRowView
    ]:
        """Compute the trial balance over POSTED journals, via the engine."""
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

        rows = trial_balance(
            list(engine_accounts.values()), postings, base_currency=base_currency
        )
        return [
            TrialBalanceRowView(
                account_code=r.account.code,
                account_name=r.account.name,
                debit_minor=r.debit.minor_units,
                credit_minor=r.credit.minor_units,
            )
            for r in rows
        ]
