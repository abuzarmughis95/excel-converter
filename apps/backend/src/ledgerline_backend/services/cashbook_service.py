"""Cashbook service — bank accounts, statement import, and posting to the ledger.

Closes the loop from extracted bank statements to the general ledger:
  * create a bank account (tied to a GL bank account in the chart);
  * import extracted statement lines (deduped by content hash on re-import);
  * post a statement line to a balanced journal via the accounting engine
    (Dr/Cr the bank account vs. a chosen contra account), so it flows into the
    trial balance.

All money is integer minor units. Posting goes through PostingService, which
validates the double entry with the engine.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from ledgerline_backend.models import (
    BankAccount,
    BankStatementLine,
    ChartOfAccount,
)
from ledgerline_backend.services.audit import record_audit
from ledgerline_backend.services.posting_service import (
    InvalidJournalError,
    LineInput,
    PostingService,
)


class CashbookError(Exception):
    """Base class for cashbook failures."""


class BankAccountNotFoundError(CashbookError):
    """No such bank account in the company."""


class GLAccountInvalidError(CashbookError):
    """The chosen GL account does not exist / belong to the company."""


class StatementLineNotFoundError(CashbookError):
    """No such statement line on the bank account."""


class LineAlreadyPostedError(CashbookError):
    """The statement line has already been posted to a journal."""


@dataclass(frozen=True)
class ImportLineInput:
    """A statement line to import (amounts in minor units)."""

    line_date: dt.date | None
    description: str
    money_out_minor: int
    money_in_minor: int
    balance_minor: int | None


@dataclass(frozen=True)
class ImportResult:
    imported: int
    duplicates: int


@dataclass(frozen=True)
class BankAccountView:
    id: uuid.UUID
    name: str
    gl_account_id: uuid.UUID
    account_number: str | None
    sort_code: str | None
    currency: str


@dataclass(frozen=True)
class StatementLineView:
    id: uuid.UUID
    line_date: dt.date | None
    description: str
    money_out_minor: int
    money_in_minor: int
    balance_minor: int | None
    is_posted: bool


def _content_hash(line: ImportLineInput) -> str:
    parts = [
        line.line_date.isoformat() if line.line_date is not None else "",
        line.description.strip().lower(),
        str(line.money_out_minor),
        str(line.money_in_minor),
    ]
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


class CashbookService:
    """Bank accounts, statement import, and posting."""

    def __init__(self, session: Session) -> None:
        self._session = session

    # -- bank accounts ----------------------------------------------------

    def create_bank_account(
        self,
        *,
        actor_id: uuid.UUID,
        company_id: uuid.UUID,
        name: str,
        gl_account_id: uuid.UUID,
        account_number: str | None = None,
        sort_code: str | None = None,
        currency: str = "GBP",
    ) -> BankAccountView:
        """Create a bank account tied to a company GL account."""
        if not name.strip():
            raise CashbookError("Bank account name is required")
        gl = self._session.get(ChartOfAccount, gl_account_id)
        if gl is None or gl.company_id != company_id:
            raise GLAccountInvalidError
        account = BankAccount(
            company_id=company_id,
            gl_account_id=gl_account_id,
            name=name.strip(),
            account_number=account_number,
            sort_code=sort_code,
            currency=currency,
        )
        self._session.add(account)
        self._session.flush()
        record_audit(
            self._session,
            entity_type="bank_account",
            entity_id=account.id,
            action="created",
            actor_user_id=actor_id,
            company_id=company_id,
        )
        return self._account_view(account)

    def list_bank_accounts(self, company_id: uuid.UUID) -> list[BankAccountView]:
        rows = self._session.scalars(
            select(BankAccount)
            .where(BankAccount.company_id == company_id)
            .order_by(BankAccount.name)
        ).all()
        return [self._account_view(a) for a in rows]

    # -- statement import -------------------------------------------------

    def import_lines(
        self,
        *,
        actor_id: uuid.UUID,
        company_id: uuid.UUID,
        bank_account_id: uuid.UUID,
        lines: list[ImportLineInput],
    ) -> ImportResult:
        """Import statement lines, skipping duplicates (by content hash)."""
        account = self._get_account(company_id, bank_account_id)
        existing = set(
            self._session.scalars(
                select(BankStatementLine.content_hash).where(
                    BankStatementLine.bank_account_id == account.id
                )
            ).all()
        )
        imported = 0
        duplicates = 0
        seen_in_batch: set[str] = set()
        for line in lines:
            digest = _content_hash(line)
            if digest in existing or digest in seen_in_batch:
                duplicates += 1
                continue
            seen_in_batch.add(digest)
            self._session.add(
                BankStatementLine(
                    bank_account_id=account.id,
                    line_date=line.line_date,
                    description=line.description.strip(),
                    money_out_minor=line.money_out_minor,
                    money_in_minor=line.money_in_minor,
                    balance_minor=line.balance_minor,
                    content_hash=digest,
                    is_posted=False,
                )
            )
            imported += 1
        self._session.flush()
        record_audit(
            self._session,
            entity_type="bank_account",
            entity_id=account.id,
            action="statement_imported",
            actor_user_id=actor_id,
            company_id=company_id,
            reason=f"imported={imported} duplicates={duplicates}",
        )
        return ImportResult(imported=imported, duplicates=duplicates)

    def list_statement_lines(
        self, company_id: uuid.UUID, bank_account_id: uuid.UUID
    ) -> list[StatementLineView]:
        account = self._get_account(company_id, bank_account_id)
        rows = self._session.scalars(
            select(BankStatementLine)
            .where(BankStatementLine.bank_account_id == account.id)
            .order_by(BankStatementLine.line_date, BankStatementLine.created_at)
        ).all()
        return [self._line_view(r) for r in rows]

    # -- posting a line to the ledger ------------------------------------

    def post_line(
        self,
        *,
        actor_id: uuid.UUID,
        company_id: uuid.UUID,
        bank_account_id: uuid.UUID,
        line_id: uuid.UUID,
        contra_account_id: uuid.UUID,
    ) -> uuid.UUID:
        """Post a statement line to a balanced journal and return the journal id.

        Money in  -> Dr bank, Cr contra (e.g. income).
        Money out -> Dr contra (e.g. expense), Cr bank.
        """
        account = self._get_account(company_id, bank_account_id)
        line = self._session.get(BankStatementLine, line_id)
        if line is None or line.bank_account_id != account.id:
            raise StatementLineNotFoundError
        if line.is_posted:
            raise LineAlreadyPostedError

        contra = self._session.get(ChartOfAccount, contra_account_id)
        if contra is None or contra.company_id != company_id:
            raise GLAccountInvalidError

        amount = line.money_in_minor - line.money_out_minor
        if amount == 0:
            raise InvalidJournalError("Statement line has no amount to post")

        bank_gl = account.gl_account_id
        if amount > 0:
            # Money received: Dr bank, Cr contra.
            posting_lines = [
                LineInput(account_id=bank_gl, debit_minor=amount),
                LineInput(account_id=contra_account_id, credit_minor=amount),
            ]
        else:
            magnitude = -amount
            # Money paid: Dr contra, Cr bank.
            posting_lines = [
                LineInput(account_id=contra_account_id, debit_minor=magnitude),
                LineInput(account_id=bank_gl, credit_minor=magnitude),
            ]

        posting = PostingService(self._session)
        journal = posting.create(
            actor_id=actor_id,
            company_id=company_id,
            journal_date=line.line_date or dt.datetime.now(tz=dt.UTC).date(),
            lines=posting_lines,
            narrative=line.description or None,
            journal_type="bank",
        )
        posting.post(actor_id=actor_id, company_id=company_id, journal_id=journal.id)

        line.is_posted = True
        line.posted_journal_id = journal.id
        line.version += 1
        record_audit(
            self._session,
            entity_type="bank_statement_line",
            entity_id=line.id,
            action="posted",
            actor_user_id=actor_id,
            company_id=company_id,
        )
        return journal.id

    # -- helpers ----------------------------------------------------------

    def _get_account(self, company_id: uuid.UUID, bank_account_id: uuid.UUID) -> BankAccount:
        account = self._session.get(BankAccount, bank_account_id)
        if account is None or account.company_id != company_id:
            raise BankAccountNotFoundError
        return account

    @staticmethod
    def _account_view(a: BankAccount) -> BankAccountView:
        return BankAccountView(
            id=a.id,
            name=a.name,
            gl_account_id=a.gl_account_id,
            account_number=a.account_number,
            sort_code=a.sort_code,
            currency=a.currency,
        )

    @staticmethod
    def _line_view(line: BankStatementLine) -> StatementLineView:
        return StatementLineView(
            id=line.id,
            line_date=line.line_date,
            description=line.description,
            money_out_minor=line.money_out_minor,
            money_in_minor=line.money_in_minor,
            balance_minor=line.balance_minor,
            is_posted=line.is_posted,
        )
