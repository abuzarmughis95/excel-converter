"""Journal (double-entry transaction) endpoints + trial balance.

Company-scoped, RBAC-enforced (read = any member, write = bookkeeper+). Posting
is validated by the accounting engine, so an unbalanced journal is rejected with
422 and never persisted in a posted state.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator

from ledgerline_backend.dependencies import CurrentUserDep, SessionDep
from ledgerline_backend.models import CompanyMembership
from ledgerline_backend.models.membership import ROLE_BOOKKEEPER, ROLE_READONLY
from ledgerline_backend.security.rbac import require_company_role
from ledgerline_backend.services.posting_service import (
    AlreadyPostedError,
    InvalidJournalError,
    JournalNotFoundError,
    JournalView,
    LineInput,
    NotPostedError,
    PostingService,
    UnbalancedJournalError,
)
from ledgerline_backend.services.reports_service import ReportsService
from ledgerline_backend.services.vat_service import VatService

router = APIRouter(prefix="/companies/{company_id}", tags=["journals"])

ReadMembership = Annotated[CompanyMembership, Depends(require_company_role(ROLE_READONLY))]
WriteMembership = Annotated[CompanyMembership, Depends(require_company_role(ROLE_BOOKKEEPER))]


_VAT_CODES = {"SR", "RR", "ZR", "EX", "EC"}


class JournalLineInput(BaseModel):
    account_id: uuid.UUID
    debit_minor: int = Field(ge=0, default=0)
    credit_minor: int = Field(ge=0, default=0)
    narrative: str | None = Field(default=None, max_length=512)
    vat_code: str | None = Field(default=None, max_length=8)
    vat_minor: int = Field(ge=0, default=0)

    @field_validator("vat_code")
    @classmethod
    def _check_vat_code(cls, value: str | None) -> str | None:
        if value is not None and value not in _VAT_CODES:
            raise ValueError(f"unknown VAT code {value!r}")
        return value


class CreateJournalRequest(BaseModel):
    journal_date: dt.date
    lines: list[JournalLineInput] = Field(min_length=2)
    currency: str = Field(default="GBP", min_length=3, max_length=3)
    reference: str | None = Field(default=None, max_length=64)
    narrative: str | None = Field(default=None, max_length=1024)


class UnpostRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=1024)


class JournalLineResponse(BaseModel):
    line_no: int
    account_id: uuid.UUID
    account_code: str
    account_name: str
    debit_minor: int
    credit_minor: int
    narrative: str | None


class JournalResponse(BaseModel):
    id: uuid.UUID
    journal_date: dt.date
    journal_type: str
    reference: str | None
    narrative: str | None
    currency: str
    is_posted: bool
    lines: list[JournalLineResponse]


class TrialBalanceRowResponse(BaseModel):
    account_code: str
    account_name: str
    debit_minor: int
    credit_minor: int


class ReportLineResponse(BaseModel):
    account_code: str
    account_name: str
    amount_minor: int


class ProfitAndLossResponse(BaseModel):
    income: list[ReportLineResponse]
    expenses: list[ReportLineResponse]
    total_income_minor: int
    total_expenses_minor: int
    net_profit_minor: int


class BalanceSheetResponse(BaseModel):
    assets: list[ReportLineResponse]
    liabilities: list[ReportLineResponse]
    equity: list[ReportLineResponse]
    total_assets_minor: int
    total_liabilities_minor: int
    total_equity_minor: int
    retained_earnings_minor: int


def _journal_response(v: JournalView) -> JournalResponse:
    return JournalResponse(
        id=v.id,
        journal_date=v.journal_date,
        journal_type=v.journal_type,
        reference=v.reference,
        narrative=v.narrative,
        currency=v.currency,
        is_posted=v.is_posted,
        lines=[
            JournalLineResponse(
                line_no=ln.line_no,
                account_id=ln.account_id,
                account_code=ln.account_code,
                account_name=ln.account_name,
                debit_minor=ln.debit_minor,
                credit_minor=ln.credit_minor,
                narrative=ln.narrative,
            )
            for ln in v.lines
        ],
    )


def _raise_journal_error(exc: Exception) -> None:
    if isinstance(exc, UnbalancedJournalError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Journal does not balance (debits must equal credits)",
        ) from exc
    if isinstance(exc, InvalidJournalError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    if isinstance(exc, JournalNotFoundError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Journal not found"
        ) from exc
    if isinstance(exc, AlreadyPostedError | NotPostedError):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc) or "Journal is in an invalid state for this action",
        ) from exc
    raise exc  # pragma: no cover


@router.post("/journals", response_model=JournalResponse, status_code=status.HTTP_201_CREATED)
def create_journal(
    company_id: uuid.UUID,
    body: CreateJournalRequest,
    current_user: CurrentUserDep,
    membership: WriteMembership,
    session: SessionDep,
) -> JournalResponse:
    """Create a balanced draft journal (validated by the engine)."""
    try:
        journal = PostingService(session).create(
            actor_id=current_user.id,
            company_id=company_id,
            journal_date=body.journal_date,
            currency=body.currency.upper(),
            reference=body.reference,
            narrative=body.narrative,
            lines=[
                LineInput(
                    account_id=ln.account_id,
                    debit_minor=ln.debit_minor,
                    credit_minor=ln.credit_minor,
                    narrative=ln.narrative,
                    vat_code=ln.vat_code,
                    vat_minor=ln.vat_minor,
                )
                for ln in body.lines
            ],
        )
    except (UnbalancedJournalError, InvalidJournalError) as exc:
        _raise_journal_error(exc)
    return _journal_response(journal)


@router.get("/journals", response_model=list[JournalResponse])
def list_journals(
    company_id: uuid.UUID,
    membership: ReadMembership,
    session: SessionDep,
    posted_only: bool = False,
) -> list[JournalResponse]:
    """List the company's journals."""
    journals = PostingService(session).list_for_company(company_id, posted_only=posted_only)
    return [_journal_response(j) for j in journals]


@router.get("/journals/{journal_id}", response_model=JournalResponse)
def get_journal(
    company_id: uuid.UUID,
    journal_id: uuid.UUID,
    membership: ReadMembership,
    session: SessionDep,
) -> JournalResponse:
    """Read a single journal."""
    try:
        return _journal_response(PostingService(session).get(company_id, journal_id))
    except JournalNotFoundError as exc:
        _raise_journal_error(exc)
        raise  # unreachable; keeps the type checker happy


@router.post("/journals/{journal_id}/post", response_model=JournalResponse)
def post_journal(
    company_id: uuid.UUID,
    journal_id: uuid.UUID,
    current_user: CurrentUserDep,
    membership: WriteMembership,
    session: SessionDep,
) -> JournalResponse:
    """Post a draft journal (bookkeeper+). Re-validated by the engine."""
    try:
        journal = PostingService(session).post(
            actor_id=current_user.id, company_id=company_id, journal_id=journal_id
        )
    except (
        JournalNotFoundError,
        AlreadyPostedError,
        UnbalancedJournalError,
        InvalidJournalError,
    ) as exc:
        _raise_journal_error(exc)
    return _journal_response(journal)


@router.post("/journals/{journal_id}/unpost", response_model=JournalResponse)
def unpost_journal(
    company_id: uuid.UUID,
    journal_id: uuid.UUID,
    body: UnpostRequest,
    current_user: CurrentUserDep,
    membership: WriteMembership,
    session: SessionDep,
) -> JournalResponse:
    """Unpost a posted journal (bookkeeper+; reason required; audited)."""
    try:
        journal = PostingService(session).unpost(
            actor_id=current_user.id,
            company_id=company_id,
            journal_id=journal_id,
            reason=body.reason,
        )
    except (JournalNotFoundError, NotPostedError, InvalidJournalError) as exc:
        _raise_journal_error(exc)
    return _journal_response(journal)


@router.get("/trial-balance", response_model=list[TrialBalanceRowResponse])
def trial_balance(
    company_id: uuid.UUID,
    membership: ReadMembership,
    session: SessionDep,
) -> list[TrialBalanceRowResponse]:
    """Trial balance over posted journals, computed by the engine."""
    rows = ReportsService(session).trial_balance(company_id)
    return [
        TrialBalanceRowResponse(
            account_code=r.account_code,
            account_name=r.account_name,
            debit_minor=r.debit_minor,
            credit_minor=r.credit_minor,
        )
        for r in rows
    ]


def _report_lines(lines: list) -> list[ReportLineResponse]:  # type: ignore[type-arg]
    return [
        ReportLineResponse(
            account_code=line.account_code,
            account_name=line.account_name,
            amount_minor=line.amount_minor,
        )
        for line in lines
    ]


@router.get("/profit-and-loss", response_model=ProfitAndLossResponse)
def profit_and_loss(
    company_id: uuid.UUID,
    membership: ReadMembership,
    session: SessionDep,
) -> ProfitAndLossResponse:
    """Profit & Loss over posted journals, computed by the engine."""
    pnl = ReportsService(session).profit_and_loss(company_id)
    return ProfitAndLossResponse(
        income=_report_lines(pnl.income),
        expenses=_report_lines(pnl.expenses),
        total_income_minor=pnl.total_income_minor,
        total_expenses_minor=pnl.total_expenses_minor,
        net_profit_minor=pnl.net_profit_minor,
    )


@router.get("/balance-sheet", response_model=BalanceSheetResponse)
def balance_sheet(
    company_id: uuid.UUID,
    membership: ReadMembership,
    session: SessionDep,
) -> BalanceSheetResponse:
    """Balance Sheet over posted journals, computed by the engine."""
    bs = ReportsService(session).balance_sheet(company_id)
    return BalanceSheetResponse(
        assets=_report_lines(bs.assets),
        liabilities=_report_lines(bs.liabilities),
        equity=_report_lines(bs.equity),
        total_assets_minor=bs.total_assets_minor,
        total_liabilities_minor=bs.total_liabilities_minor,
        total_equity_minor=bs.total_equity_minor,
        retained_earnings_minor=bs.retained_earnings_minor,
    )


class VatReturnResponse(BaseModel):
    box1_minor: int
    box2_minor: int
    box3_minor: int
    box4_minor: int
    box5_minor: int
    box6_minor: int
    box7_minor: int
    box8_minor: int
    box9_minor: int


@router.get("/vat-return", response_model=VatReturnResponse)
def vat_return(
    company_id: uuid.UUID,
    membership: ReadMembership,
    session: SessionDep,
) -> VatReturnResponse:
    """The 9-box UK VAT return over posted journals, computed by the engine."""
    vr = VatService(session).vat_return(company_id)
    return VatReturnResponse(
        box1_minor=vr.box1_minor,
        box2_minor=vr.box2_minor,
        box3_minor=vr.box3_minor,
        box4_minor=vr.box4_minor,
        box5_minor=vr.box5_minor,
        box6_minor=vr.box6_minor,
        box7_minor=vr.box7_minor,
        box8_minor=vr.box8_minor,
        box9_minor=vr.box9_minor,
    )
