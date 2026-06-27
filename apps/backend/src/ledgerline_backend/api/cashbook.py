"""Cashbook endpoints — bank accounts, statement import, and posting to ledger.

Company-scoped, RBAC-enforced (read = any member, write = bookkeeper+). Posting a
statement line creates a balanced journal via the accounting engine.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from ledgerline_backend.dependencies import CurrentUserDep, SessionDep
from ledgerline_backend.models import CompanyMembership
from ledgerline_backend.models.membership import ROLE_BOOKKEEPER, ROLE_READONLY
from ledgerline_backend.security.rbac import require_company_role
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

router = APIRouter(prefix="/companies/{company_id}/bank-accounts", tags=["cashbook"])

ReadMembership = Annotated[CompanyMembership, Depends(require_company_role(ROLE_READONLY))]
WriteMembership = Annotated[CompanyMembership, Depends(require_company_role(ROLE_BOOKKEEPER))]


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
