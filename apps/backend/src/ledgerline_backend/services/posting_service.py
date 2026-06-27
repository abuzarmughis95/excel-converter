"""Posting service — wires the accounting engine into the backend (AC-08).

Creates double-entry journals, validates them with the canonical engine
(``Posting`` is unconstructable unless balanced), persists journal + lines, and
posts / unposts. Because validation goes through the SAME engine the desktop
sidecar uses, an unbalanced journal can never be persisted in a posted state and
the backend can never disagree with the engine about what balances.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass

from ledgerline_engine.api import (
    Account,
    AccountType,
    Money,
    Posting,
    PostingError,
    PostingLine,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from ledgerline_backend.models import ChartOfAccount, Journal, JournalLine
from ledgerline_backend.services.audit import record_audit
from ledgerline_backend.services.period_service import PeriodService
from ledgerline_backend.util.time import utcnow

_ENGINE_TYPE = {
    "asset": AccountType.ASSET,
    "liability": AccountType.LIABILITY,
    "equity": AccountType.EQUITY,
    "income": AccountType.INCOME,
    "expense": AccountType.EXPENSE,
}


class JournalError(Exception):
    """Base class for journal/posting failures."""


class UnbalancedJournalError(JournalError):
    """The journal's lines do not balance (debits != credits)."""


class InvalidJournalError(JournalError):
    """The journal is malformed (no lines, unknown/inactive account, etc.)."""


class JournalNotFoundError(JournalError):
    """No such journal in the company."""


class AlreadyPostedError(JournalError):
    """The journal is already posted (posted journals are immutable)."""


class NotPostedError(JournalError):
    """The journal is not posted, so it cannot be unposted."""


@dataclass(frozen=True)
class LineInput:
    """One requested journal line (amounts in integer minor units)."""

    account_id: uuid.UUID
    debit_minor: int = 0
    credit_minor: int = 0
    narrative: str | None = None
    # Optional VAT treatment: when vat_code is set, this line is the taxable
    # supply (its amount is the NET) and vat_minor is the VAT on it.
    vat_code: str | None = None
    vat_minor: int = 0


@dataclass(frozen=True)
class JournalView:
    """A journal with its lines for presentation."""

    id: uuid.UUID
    journal_date: dt.date
    journal_type: str
    reference: str | None
    narrative: str | None
    currency: str
    is_posted: bool
    lines: list[JournalLineView]


@dataclass(frozen=True)
class JournalLineView:
    line_no: int
    account_id: uuid.UUID
    account_code: str
    account_name: str
    debit_minor: int
    credit_minor: int
    narrative: str | None


# Backwards-compatible alias for the shared helper.
_utcnow = utcnow


class PostingService:
    """Journal creation and posting, validated by the accounting engine."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def _load_accounts(
        self, company_id: uuid.UUID, account_ids: set[uuid.UUID]
    ) -> dict[uuid.UUID, ChartOfAccount]:
        rows = self._session.scalars(
            select(ChartOfAccount).where(
                ChartOfAccount.company_id == company_id,
                ChartOfAccount.id.in_(account_ids),
            )
        ).all()
        return {a.id: a for a in rows}

    def _validate_with_engine(
        self,
        accounts: dict[uuid.UUID, ChartOfAccount],
        lines: list[LineInput],
        currency: str,
    ) -> None:
        """Build engine objects so the engine enforces the balance invariant.

        Raises UnbalancedJournalError / InvalidJournalError. We deliberately do
        NOT persist anything here — this is pure validation through the engine.
        """
        engine_lines: list[PostingLine] = []
        for ln in lines:
            account = accounts.get(ln.account_id)
            if account is None:
                msg = "Line references an unknown account"
                raise InvalidJournalError(msg)
            if not account.is_active:
                msg = f"Account {account.code} is not active"
                raise InvalidJournalError(msg)
            is_debit = ln.debit_minor > 0
            amount_minor = ln.debit_minor if is_debit else ln.credit_minor
            engine_account = Account(
                code=account.code,
                name=account.name,
                account_type=_ENGINE_TYPE[account.account_type],
                is_active=account.is_active,
            )
            money = Money(amount_minor, currency)
            engine_lines.append(
                PostingLine(
                    account=engine_account,
                    amount=money,
                    base_amount=money,
                    is_debit=is_debit,
                )
            )
        try:
            Posting.of(engine_lines, base_currency=currency)
        except PostingError as exc:
            # The engine's balance/line invariants are the source of truth.
            from ledgerline_engine.api import UnbalancedPostingError

            if isinstance(exc, UnbalancedPostingError):
                raise UnbalancedJournalError(str(exc)) from exc
            raise InvalidJournalError(str(exc)) from exc

    def create(
        self,
        *,
        actor_id: uuid.UUID,
        company_id: uuid.UUID,
        journal_date: dt.date,
        lines: list[LineInput],
        currency: str = "GBP",
        reference: str | None = None,
        narrative: str | None = None,
        journal_type: str = "journal",
    ) -> JournalView:
        """Create a balanced draft journal. The engine validates the balance."""
        if len(lines) < 2:
            msg = "A journal needs at least two lines"
            raise InvalidJournalError(msg)
        for ln in lines:
            if ln.debit_minor < 0 or ln.credit_minor < 0:
                raise InvalidJournalError("Line amounts must be non-negative")
            if (ln.debit_minor > 0) == (ln.credit_minor > 0):
                raise InvalidJournalError("Each line is a debit XOR a credit")

        accounts = self._load_accounts(company_id, {ln.account_id for ln in lines})
        self._validate_with_engine(accounts, lines, currency)

        journal = Journal(
            company_id=company_id,
            journal_date=journal_date,
            journal_type=journal_type,
            reference=reference,
            narrative=narrative,
            currency=currency,
            is_posted=False,
        )
        self._session.add(journal)
        self._session.flush()

        for i, ln in enumerate(lines, start=1):
            self._session.add(
                JournalLine(
                    journal_id=journal.id,
                    line_no=i,
                    account_id=ln.account_id,
                    debit_minor=ln.debit_minor,
                    credit_minor=ln.credit_minor,
                    base_debit_minor=ln.debit_minor,
                    base_credit_minor=ln.credit_minor,
                    narrative=ln.narrative,
                    vat_code=ln.vat_code,
                    vat_minor=ln.vat_minor,
                )
            )
        self._session.flush()
        record_audit(
            self._session,
            entity_type="journal",
            entity_id=journal.id,
            action="created",
            actor_user_id=actor_id,
            company_id=company_id,
        )
        return self._view(journal)

    def post(
        self, *, actor_id: uuid.UUID, company_id: uuid.UUID, journal_id: uuid.UUID
    ) -> JournalView:
        """Post a draft journal, re-validating the balance via the engine."""
        journal = self._get(company_id, journal_id)
        if journal.is_posted:
            raise AlreadyPostedError
        # Block posting into a soft-closed or locked period.
        PeriodService(self._session).assert_date_postable(
            company_id, journal.journal_date
        )

        lines = self._lines(journal_id)
        inputs = [
            LineInput(
                account_id=ln.account_id,
                debit_minor=ln.debit_minor,
                credit_minor=ln.credit_minor,
            )
            for ln in lines
        ]
        accounts = self._load_accounts(company_id, {ln.account_id for ln in lines})
        # Defence in depth: re-validate at post time.
        self._validate_with_engine(accounts, inputs, journal.currency)

        journal.is_posted = True
        journal.posted_at = _utcnow()
        journal.posted_by = actor_id
        journal.version += 1
        record_audit(
            self._session,
            entity_type="journal",
            entity_id=journal.id,
            action="posted",
            actor_user_id=actor_id,
            company_id=company_id,
        )
        return self._view(journal)

    def unpost(
        self,
        *,
        actor_id: uuid.UUID,
        company_id: uuid.UUID,
        journal_id: uuid.UUID,
        reason: str,
    ) -> JournalView:
        """Unpost a posted journal (privileged; requires a reason; audited)."""
        if not reason.strip():
            raise InvalidJournalError("Unposting requires a reason")
        journal = self._get(company_id, journal_id)
        if not journal.is_posted:
            raise NotPostedError
        # A locked/soft-closed period is final: correct via a reversing entry,
        # not by unposting the original.
        PeriodService(self._session).assert_date_postable(
            company_id, journal.journal_date
        )

        journal.is_posted = False
        journal.posted_at = None
        journal.posted_by = None
        journal.version += 1
        record_audit(
            self._session,
            entity_type="journal",
            entity_id=journal.id,
            action="unposted",
            actor_user_id=actor_id,
            company_id=company_id,
            reason=reason,
        )
        return self._view(journal)

    def reverse(
        self,
        *,
        actor_id: uuid.UUID,
        company_id: uuid.UUID,
        journal_id: uuid.UUID,
        reversal_date: dt.date | None = None,
        reason: str,
    ) -> JournalView:
        """Create and post a reversing journal that cancels a posted journal.

        The reversal mirrors the original with debits and credits swapped. It is
        dated ``reversal_date`` (default: the original's date) and must itself
        land in a postable period — this is the correct way to fix an error in a
        locked period, leaving the original untouched and fully audited.
        """
        if not reason.strip():
            raise InvalidJournalError("A reversal requires a reason")
        original = self._get(company_id, journal_id)
        if not original.is_posted:
            raise NotPostedError
        lines = self._lines(journal_id)
        # Swap debit and credit on every line to reverse the entry.
        reversed_inputs = [
            LineInput(
                account_id=ln.account_id,
                debit_minor=ln.credit_minor,
                credit_minor=ln.debit_minor,
                narrative=ln.narrative,
                vat_code=ln.vat_code,
                vat_minor=ln.vat_minor,
            )
            for ln in lines
        ]
        ref = f"REV:{original.reference}" if original.reference else "REV"
        created = self.create(
            actor_id=actor_id,
            company_id=company_id,
            journal_date=reversal_date or original.journal_date,
            lines=reversed_inputs,
            currency=original.currency,
            reference=ref[:64],
            narrative=f"Reversal of {original.id}: {reason}"[:1024],
            journal_type="reversal",
        )
        posted = self.post(
            actor_id=actor_id, company_id=company_id, journal_id=created.id
        )
        record_audit(
            self._session,
            entity_type="journal",
            entity_id=original.id,
            action="reversed",
            actor_user_id=actor_id,
            company_id=company_id,
            reason=reason,
        )
        return posted

    def list_for_company(
        self, company_id: uuid.UUID, *, posted_only: bool = False
    ) -> list[JournalView]:
        stmt = select(Journal).where(Journal.company_id == company_id)
        if posted_only:
            stmt = stmt.where(Journal.is_posted.is_(True))
        stmt = stmt.order_by(Journal.journal_date.desc(), Journal.created_at.desc())
        return [self._view(j) for j in self._session.scalars(stmt).all()]

    def get(self, company_id: uuid.UUID, journal_id: uuid.UUID) -> JournalView:
        return self._view(self._get(company_id, journal_id))

    # -- helpers ----------------------------------------------------------

    def _get(self, company_id: uuid.UUID, journal_id: uuid.UUID) -> Journal:
        journal = self._session.get(Journal, journal_id)
        if journal is None or journal.company_id != company_id:
            raise JournalNotFoundError
        return journal

    def _lines(self, journal_id: uuid.UUID) -> list[JournalLine]:
        return list(
            self._session.scalars(
                select(JournalLine)
                .where(JournalLine.journal_id == journal_id)
                .order_by(JournalLine.line_no)
            ).all()
        )

    def _view(self, journal: Journal) -> JournalView:
        lines = self._lines(journal.id)
        account_ids = {ln.account_id for ln in lines}
        accounts = {
            a.id: a
            for a in self._session.scalars(
                select(ChartOfAccount).where(ChartOfAccount.id.in_(account_ids))
            ).all()
        }
        return JournalView(
            id=journal.id,
            journal_date=journal.journal_date,
            journal_type=journal.journal_type,
            reference=journal.reference,
            narrative=journal.narrative,
            currency=journal.currency,
            is_posted=journal.is_posted,
            lines=[
                JournalLineView(
                    line_no=ln.line_no,
                    account_id=ln.account_id,
                    account_code=accounts[ln.account_id].code if ln.account_id in accounts else "?",
                    account_name=accounts[ln.account_id].name if ln.account_id in accounts else "?",
                    debit_minor=ln.debit_minor,
                    credit_minor=ln.credit_minor,
                    narrative=ln.narrative,
                )
                for ln in lines
            ],
        )
