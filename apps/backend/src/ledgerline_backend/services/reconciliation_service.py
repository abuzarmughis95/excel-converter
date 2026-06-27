"""Bank reconciliation service.

Lets a user tick off the ledger entries that hit a bank account's GL account
against the bank statement, and shows a reconciliation summary: the full ledger
balance, the reconciled balance (cleared items only), and the difference against
a statement closing balance the user supplies.

Reconciliation state is held in BankReconciliationMark rows (one per cleared
journal line) so the immutable journal lines are never mutated.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from ledgerline_backend.models import (
    BankAccount,
    BankReconciliationMark,
    BankStatementLine,
    Journal,
    JournalLine,
)
from ledgerline_backend.services.audit import record_audit


class ReconciliationError(Exception):
    """Base class for reconciliation failures."""


class BankAccountNotFoundError(ReconciliationError):
    """No such bank account in the company."""


class JournalLineNotFoundError(ReconciliationError):
    """The journal line does not exist or does not hit this bank account."""


@dataclass(frozen=True)
class ReconcilableLine:
    """A ledger entry on the bank account, with its reconciled state."""

    journal_line_id: uuid.UUID
    journal_id: uuid.UUID
    line_date: str | None
    narrative: str | None
    # Positive = money into the bank (debit on an asset account); negative = out.
    amount_minor: int
    reconciled: bool


@dataclass(frozen=True)
class ReconciliationSummary:
    """Totals for the bank reconciliation."""

    ledger_balance_minor: int
    reconciled_balance_minor: int
    unreconciled_count: int
    statement_balance_minor: int | None
    difference_minor: int | None


@dataclass(frozen=True)
class MatchSuggestion:
    """A suggested pairing of an unreconciled ledger entry to a statement line."""

    journal_line_id: uuid.UUID
    ledger_date: str | None
    ledger_narrative: str | None
    statement_line_id: uuid.UUID
    statement_date: str | None
    statement_description: str
    amount_minor: int
    # Confidence: "exact" (same amount and date) or "amount" (amount only).
    confidence: str
    days_apart: int | None


class ReconciliationService:
    """Bank reconciliation for a company's bank account."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def _get_account(self, company_id: uuid.UUID, bank_account_id: uuid.UUID) -> BankAccount:
        account = self._session.get(BankAccount, bank_account_id)
        if account is None or account.company_id != company_id:
            raise BankAccountNotFoundError
        return account

    def _bank_lines(self, account: BankAccount) -> list[tuple[JournalLine, Journal]]:
        """All POSTED journal lines hitting this bank account's GL account."""
        rows = self._session.execute(
            select(JournalLine, Journal)
            .join(Journal, Journal.id == JournalLine.journal_id)
            .where(
                JournalLine.account_id == account.gl_account_id,
                Journal.company_id == account.company_id,
                Journal.is_posted.is_(True),
            )
            .order_by(Journal.journal_date, Journal.created_at, JournalLine.line_no)
        ).all()
        return [(line, journal) for line, journal in rows]

    def _marked_ids(self, account: BankAccount) -> set[uuid.UUID]:
        return set(
            self._session.scalars(
                select(BankReconciliationMark.journal_line_id).where(
                    BankReconciliationMark.bank_account_id == account.id
                )
            ).all()
        )

    @staticmethod
    def _signed(line: JournalLine) -> int:
        """Money into the bank account is positive (debit on an asset)."""
        return line.debit_minor - line.credit_minor

    def list_lines(
        self, company_id: uuid.UUID, bank_account_id: uuid.UUID
    ) -> list[ReconcilableLine]:
        account = self._get_account(company_id, bank_account_id)
        marked = self._marked_ids(account)
        result = []
        for line, journal in self._bank_lines(account):
            result.append(
                ReconcilableLine(
                    journal_line_id=line.id,
                    journal_id=journal.id,
                    line_date=journal.journal_date.isoformat(),
                    narrative=journal.narrative,
                    amount_minor=self._signed(line),
                    reconciled=line.id in marked,
                )
            )
        return result

    def set_reconciled(
        self,
        *,
        actor_id: uuid.UUID,
        company_id: uuid.UUID,
        bank_account_id: uuid.UUID,
        journal_line_id: uuid.UUID,
        reconciled: bool,
    ) -> None:
        """Tick (or untick) a journal line as reconciled for this bank account."""
        account = self._get_account(company_id, bank_account_id)
        # Verify the line actually hits this bank account.
        valid = {line.id for line, _ in self._bank_lines(account)}
        if journal_line_id not in valid:
            raise JournalLineNotFoundError

        existing = self._session.scalar(
            select(BankReconciliationMark).where(
                BankReconciliationMark.bank_account_id == account.id,
                BankReconciliationMark.journal_line_id == journal_line_id,
            )
        )
        if reconciled and existing is None:
            self._session.add(
                BankReconciliationMark(
                    bank_account_id=account.id, journal_line_id=journal_line_id
                )
            )
            action = "reconciled"
        elif not reconciled and existing is not None:
            self._session.delete(existing)
            action = "unreconciled"
        else:
            return  # no change

        self._session.flush()
        record_audit(
            self._session,
            entity_type="bank_statement_line",
            entity_id=journal_line_id,
            action=f"line_{action}",
            actor_user_id=actor_id,
            company_id=company_id,
        )

    def summary(
        self,
        company_id: uuid.UUID,
        bank_account_id: uuid.UUID,
        *,
        statement_balance_minor: int | None = None,
    ) -> ReconciliationSummary:
        account = self._get_account(company_id, bank_account_id)
        marked = self._marked_ids(account)
        ledger = 0
        reconciled = 0
        unreconciled_count = 0
        for line, _journal in self._bank_lines(account):
            signed = self._signed(line)
            ledger += signed
            if line.id in marked:
                reconciled += signed
            else:
                unreconciled_count += 1
        difference = (
            statement_balance_minor - reconciled
            if statement_balance_minor is not None
            else None
        )
        return ReconciliationSummary(
            ledger_balance_minor=ledger,
            reconciled_balance_minor=reconciled,
            unreconciled_count=unreconciled_count,
            statement_balance_minor=statement_balance_minor,
            difference_minor=difference,
        )

    def suggest_matches(
        self,
        company_id: uuid.UUID,
        bank_account_id: uuid.UUID,
        *,
        max_days: int = 5,
    ) -> list[MatchSuggestion]:
        """Suggest matches between unreconciled ledger entries and statement lines.

        For each unreconciled ledger entry on the bank account, find a statement
        line with the SAME signed amount, preferring the closest date within
        ``max_days``. Each statement line is suggested at most once (greedy:
        exact date matches are assigned first). The user confirms a suggestion,
        which then reconciles the ledger entry.
        """
        account = self._get_account(company_id, bank_account_id)
        marked = self._marked_ids(account)

        # Unreconciled ledger entries, keyed by signed amount.
        unreconciled = [
            (line, journal)
            for line, journal in self._bank_lines(account)
            if line.id not in marked
        ]
        # Candidate statement lines (signed = money_in - money_out).
        statement_lines = list(
            self._session.scalars(
                select(BankStatementLine).where(
                    BankStatementLine.bank_account_id == account.id
                )
            ).all()
        )
        used_statement: set[uuid.UUID] = set()

        def day_distance(a: dt.date | None, b: dt.date | None) -> int | None:
            if a is None or b is None:
                return None
            return abs((a - b).days)

        suggestions: list[MatchSuggestion] = []
        # Sort so the entries most likely to have an exact-date match are handled
        # first; this makes the greedy assignment stable and exact-biased.
        for line, journal in unreconciled:
            signed = self._signed(line)
            best: BankStatementLine | None = None
            best_days: int | None = None
            for stmt in statement_lines:
                if stmt.id in used_statement:
                    continue
                stmt_signed = stmt.money_in_minor - stmt.money_out_minor
                if stmt_signed != signed:
                    continue
                days = day_distance(journal.journal_date, stmt.line_date)
                # Reject if a date is known on both sides and too far apart.
                if days is not None and days > max_days:
                    continue
                # Prefer the closest known date; unknown-date lines rank last.
                if best is None:
                    best, best_days = stmt, days
                elif days is not None and (best_days is None or days < best_days):
                    best, best_days = stmt, days
            if best is None:
                continue
            used_statement.add(best.id)
            suggestions.append(
                MatchSuggestion(
                    journal_line_id=line.id,
                    ledger_date=journal.journal_date.isoformat(),
                    ledger_narrative=journal.narrative,
                    statement_line_id=best.id,
                    statement_date=best.line_date.isoformat() if best.line_date else None,
                    statement_description=best.description,
                    amount_minor=signed,
                    confidence="exact" if best_days == 0 else "amount",
                    days_apart=best_days,
                )
            )
        return suggestions
