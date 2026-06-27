"""Cashbook endpoints — bank accounts, statement import, and posting to ledger.

Company-scoped, RBAC-enforced (read = any member, write = bookkeeper+). Posting a
statement line creates a balanced journal via the accounting engine.
"""

from __future__ import annotations

import datetime as dt
import uuid

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, Field

from ledgerline_backend.api.membership_deps import ReadMembership, WriteMembership
from ledgerline_backend.dependencies import CurrentUserDep, SessionDep
from ledgerline_backend.services.cashbook_service import (
    BankAccountNotFoundError,
    BankAccountView,
    CashbookError,
    CashbookService,
    GLAccountInvalidError,
    ImportLineInput,
    LineAlreadyPostedError,
    StatementLineNotFoundError,
    StatementLineView,
)
from ledgerline_backend.services.posting_service import InvalidJournalError
from ledgerline_backend.services.reconciliation_service import (
    BankAccountNotFoundError as ReconBankNotFound,
)
from ledgerline_backend.services.reconciliation_service import (
    JournalLineNotFoundError,
    ReconciliationService,
)

router = APIRouter(prefix="/companies/{company_id}/bank-accounts", tags=["cashbook"])


class CreateBankAccountRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    gl_account_id: uuid.UUID
    account_number: str | None = Field(default=None, max_length=34)
    sort_code: str | None = Field(default=None, max_length=16)
    currency: str = Field(default="GBP", min_length=3, max_length=3)


class BankAccountResponse(BaseModel):
    id: uuid.UUID
    name: str
    gl_account_id: uuid.UUID
    account_number: str | None
    sort_code: str | None
    currency: str


class ImportLineModel(BaseModel):
    line_date: dt.date | None = None
    description: str = Field(default="", max_length=512)
    money_out_minor: int = Field(ge=0, default=0)
    money_in_minor: int = Field(ge=0, default=0)
    balance_minor: int | None = None


class ImportLinesRequest(BaseModel):
    lines: list[ImportLineModel] = Field(min_length=1)


class ImportResultResponse(BaseModel):
    imported: int
    duplicates: int


class StatementLineResponse(BaseModel):
    id: uuid.UUID
    line_date: dt.date | None
    description: str
    money_out_minor: int
    money_in_minor: int
    balance_minor: int | None
    is_posted: bool


class PostLineRequest(BaseModel):
    contra_account_id: uuid.UUID


class PostLineResponse(BaseModel):
    journal_id: uuid.UUID


def _account_response(v: BankAccountView) -> BankAccountResponse:
    return BankAccountResponse(
        id=v.id,
        name=v.name,
        gl_account_id=v.gl_account_id,
        account_number=v.account_number,
        sort_code=v.sort_code,
        currency=v.currency,
    )


def _line_response(v: StatementLineView) -> StatementLineResponse:
    return StatementLineResponse(
        id=v.id,
        line_date=v.line_date,
        description=v.description,
        money_out_minor=v.money_out_minor,
        money_in_minor=v.money_in_minor,
        balance_minor=v.balance_minor,
        is_posted=v.is_posted,
    )


@router.post("", response_model=BankAccountResponse, status_code=status.HTTP_201_CREATED)
def create_bank_account(
    company_id: uuid.UUID,
    body: CreateBankAccountRequest,
    current_user: CurrentUserDep,
    membership: WriteMembership,
    session: SessionDep,
) -> BankAccountResponse:
    """Create a bank account tied to a GL account (bookkeeper+)."""
    try:
        account = CashbookService(session).create_bank_account(
            actor_id=current_user.id,
            company_id=company_id,
            name=body.name,
            gl_account_id=body.gl_account_id,
            account_number=body.account_number,
            sort_code=body.sort_code,
            currency=body.currency.upper(),
        )
    except GLAccountInvalidError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="The chosen general-ledger account is invalid",
        ) from exc
    except CashbookError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return _account_response(account)


@router.get("", response_model=list[BankAccountResponse])
def list_bank_accounts(
    company_id: uuid.UUID,
    membership: ReadMembership,
    session: SessionDep,
) -> list[BankAccountResponse]:
    """List the company's bank accounts."""
    return [_account_response(a) for a in CashbookService(session).list_bank_accounts(company_id)]


@router.post("/{bank_account_id}/import", response_model=ImportResultResponse)
def import_statement_lines(
    company_id: uuid.UUID,
    bank_account_id: uuid.UUID,
    body: ImportLinesRequest,
    current_user: CurrentUserDep,
    membership: WriteMembership,
    session: SessionDep,
) -> ImportResultResponse:
    """Import statement lines onto a bank account (deduped on re-import)."""
    try:
        result = CashbookService(session).import_lines(
            actor_id=current_user.id,
            company_id=company_id,
            bank_account_id=bank_account_id,
            lines=[
                ImportLineInput(
                    line_date=ln.line_date,
                    description=ln.description,
                    money_out_minor=ln.money_out_minor,
                    money_in_minor=ln.money_in_minor,
                    balance_minor=ln.balance_minor,
                )
                for ln in body.lines
            ],
        )
    except BankAccountNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Bank account not found"
        ) from exc
    return ImportResultResponse(imported=result.imported, duplicates=result.duplicates)


@router.get("/{bank_account_id}/lines", response_model=list[StatementLineResponse])
def list_statement_lines(
    company_id: uuid.UUID,
    bank_account_id: uuid.UUID,
    membership: ReadMembership,
    session: SessionDep,
) -> list[StatementLineResponse]:
    """List a bank account's imported statement lines."""
    try:
        lines = CashbookService(session).list_statement_lines(company_id, bank_account_id)
    except BankAccountNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Bank account not found"
        ) from exc
    return [_line_response(line) for line in lines]


@router.post(
    "/{bank_account_id}/lines/{line_id}/post", response_model=PostLineResponse
)
def post_statement_line(
    company_id: uuid.UUID,
    bank_account_id: uuid.UUID,
    line_id: uuid.UUID,
    body: PostLineRequest,
    current_user: CurrentUserDep,
    membership: WriteMembership,
    session: SessionDep,
) -> PostLineResponse:
    """Post a statement line to a balanced journal (Dr/Cr bank vs contra)."""
    service = CashbookService(session)
    try:
        journal_id = service.post_line(
            actor_id=current_user.id,
            company_id=company_id,
            bank_account_id=bank_account_id,
            line_id=line_id,
            contra_account_id=body.contra_account_id,
        )
    except (BankAccountNotFoundError, StatementLineNotFoundError) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Not found"
        ) from exc
    except LineAlreadyPostedError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Line already posted"
        ) from exc
    except (GLAccountInvalidError, InvalidJournalError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc) or "Invalid posting"
        ) from exc
    return PostLineResponse(journal_id=journal_id)


# -- reconciliation -------------------------------------------------------


class ReconcilableLineResponse(BaseModel):
    journal_line_id: uuid.UUID
    journal_id: uuid.UUID
    line_date: str | None
    narrative: str | None
    amount_minor: int
    reconciled: bool


class SetReconciledRequest(BaseModel):
    reconciled: bool


class ReconciliationSummaryResponse(BaseModel):
    ledger_balance_minor: int
    reconciled_balance_minor: int
    unreconciled_count: int
    statement_balance_minor: int | None
    difference_minor: int | None


@router.get("/{bank_account_id}/reconciliation", response_model=list[ReconcilableLineResponse])
def list_reconcilable_lines(
    company_id: uuid.UUID,
    bank_account_id: uuid.UUID,
    membership: ReadMembership,
    session: SessionDep,
) -> list[ReconcilableLineResponse]:
    """List the bank account's ledger entries with their reconciled state."""
    try:
        lines = ReconciliationService(session).list_lines(company_id, bank_account_id)
    except ReconBankNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Bank account not found"
        ) from exc
    return [
        ReconcilableLineResponse(
            journal_line_id=line.journal_line_id,
            journal_id=line.journal_id,
            line_date=line.line_date,
            narrative=line.narrative,
            amount_minor=line.amount_minor,
            reconciled=line.reconciled,
        )
        for line in lines
    ]


@router.post(
    "/{bank_account_id}/reconciliation/{journal_line_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def set_line_reconciled(
    company_id: uuid.UUID,
    bank_account_id: uuid.UUID,
    journal_line_id: uuid.UUID,
    body: SetReconciledRequest,
    current_user: CurrentUserDep,
    membership: WriteMembership,
    session: SessionDep,
) -> Response:
    """Tick or untick a ledger entry as reconciled (bookkeeper+)."""
    try:
        ReconciliationService(session).set_reconciled(
            actor_id=current_user.id,
            company_id=company_id,
            bank_account_id=bank_account_id,
            journal_line_id=journal_line_id,
            reconciled=body.reconciled,
        )
    except ReconBankNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Bank account not found"
        ) from exc
    except JournalLineNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Ledger entry not found"
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/{bank_account_id}/reconciliation-summary", response_model=ReconciliationSummaryResponse
)
def reconciliation_summary(
    company_id: uuid.UUID,
    bank_account_id: uuid.UUID,
    membership: ReadMembership,
    session: SessionDep,
    statement_balance_minor: int | None = None,
) -> ReconciliationSummaryResponse:
    """Reconciliation summary; pass statement_balance_minor to see the difference."""
    try:
        summary = ReconciliationService(session).summary(
            company_id, bank_account_id, statement_balance_minor=statement_balance_minor
        )
    except ReconBankNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Bank account not found"
        ) from exc
    return ReconciliationSummaryResponse(
        ledger_balance_minor=summary.ledger_balance_minor,
        reconciled_balance_minor=summary.reconciled_balance_minor,
        unreconciled_count=summary.unreconciled_count,
        statement_balance_minor=summary.statement_balance_minor,
        difference_minor=summary.difference_minor,
    )


class MatchSuggestionResponse(BaseModel):
    journal_line_id: uuid.UUID
    ledger_date: str | None
    ledger_narrative: str | None
    statement_line_id: uuid.UUID
    statement_date: str | None
    statement_description: str
    amount_minor: int
    confidence: str
    days_apart: int | None


@router.get(
    "/{bank_account_id}/reconciliation-suggestions",
    response_model=list[MatchSuggestionResponse],
)
def reconciliation_suggestions(
    company_id: uuid.UUID,
    bank_account_id: uuid.UUID,
    membership: ReadMembership,
    session: SessionDep,
    max_days: int = 5,
) -> list[MatchSuggestionResponse]:
    """Suggest matches between unreconciled ledger entries and statement lines."""
    try:
        suggestions = ReconciliationService(session).suggest_matches(
            company_id, bank_account_id, max_days=max_days
        )
    except ReconBankNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Bank account not found"
        ) from exc
    return [
        MatchSuggestionResponse(
            journal_line_id=s.journal_line_id,
            ledger_date=s.ledger_date,
            ledger_narrative=s.ledger_narrative,
            statement_line_id=s.statement_line_id,
            statement_date=s.statement_date,
            statement_description=s.statement_description,
            amount_minor=s.amount_minor,
            confidence=s.confidence,
            days_apart=s.days_apart,
        )
        for s in suggestions
    ]
