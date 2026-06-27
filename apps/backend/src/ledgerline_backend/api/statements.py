"""Bank statement extraction endpoint.

Accepts a PDF bank statement upload (company-scoped, bookkeeper+), runs OpenAI
vision extraction, and returns the structured account summary + transaction
lines. The OpenAI client is built from settings; when no API key is configured
the endpoint returns 503 so the UI can explain the feature is unavailable.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from pydantic import BaseModel

from ledgerline_backend.dependencies import SettingsDep
from ledgerline_backend.models import CompanyMembership
from ledgerline_backend.models.membership import ROLE_BOOKKEEPER
from ledgerline_backend.security.rbac import require_company_role
from ledgerline_backend.services.statement_extraction import (
    ExtractedStatement,
    ModelClient,
    OpenAIStatementClient,
    StatementExtractionError,
    extract_statement,
)

router = APIRouter(prefix="/companies/{company_id}/statements", tags=["statements"])

WriteMembership = Annotated[CompanyMembership, Depends(require_company_role(ROLE_BOOKKEEPER))]


class StatementLineResponse(BaseModel):
    date: str | None
    description: str
    money_out_minor: int
    money_in_minor: int
    balance_minor: int | None


class StatementSummaryResponse(BaseModel):
    account_name: str | None
    account_number: str | None
    sort_code: str | None
    period_start: str | None
    period_end: str | None
    opening_balance_minor: int | None
    closing_balance_minor: int | None


class ExtractStatementResponse(BaseModel):
    currency: str
    reconciled: bool
    summary: StatementSummaryResponse
    lines: list[StatementLineResponse]


def _to_response(result: ExtractedStatement) -> ExtractStatementResponse:
    s = result.summary
    return ExtractStatementResponse(
        currency=result.currency,
        reconciled=result.reconciled,
        summary=StatementSummaryResponse(
            account_name=s.account_name,
            account_number=s.account_number,
            sort_code=s.sort_code,
            period_start=s.period_start,
            period_end=s.period_end,
            opening_balance_minor=s.opening_balance_minor,
            closing_balance_minor=s.closing_balance_minor,
        ),
        lines=[
            StatementLineResponse(
                date=ln.date,
                description=ln.description,
                money_out_minor=ln.money_out_minor,
                money_in_minor=ln.money_in_minor,
                balance_minor=ln.balance_minor,
            )
            for ln in result.lines
        ],
    )


def _build_client(request: Request, settings: SettingsDep) -> ModelClient:
    """Resolve the model client.

    Tests may inject a fake by setting ``app.state.statement_client``. Otherwise
    an OpenAI-backed client is built from settings, or 503 if no key is set.
    """
    injected = getattr(request.app.state, "statement_client", None)
    if injected is not None:
        return injected  # type: ignore[no-any-return]
    if not settings.ocr_enabled or settings.openai_api_key is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Statement extraction is not configured (no OpenAI API key)",
        )
    return OpenAIStatementClient(settings.openai_api_key)


@router.post("/extract", response_model=ExtractStatementResponse)
async def extract_bank_statement(
    company_id: uuid.UUID,
    membership: WriteMembership,
    settings: SettingsDep,
    request: Request,
    file: Annotated[UploadFile, File()],
) -> ExtractStatementResponse:
    """Upload a bank statement PDF and extract its summary + transaction lines."""
    if file.content_type not in ("application/pdf", "application/octet-stream"):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Only PDF bank statements are supported",
        )
    pdf_bytes = await file.read()
    if len(pdf_bytes) == 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Empty file"
        )
    if len(pdf_bytes) > settings.openai_max_upload_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Statement file is too large",
        )

    client = _build_client(request, settings)
    try:
        result = extract_statement(
            pdf_bytes=pdf_bytes, model=settings.openai_model, client=client
        )
    except StatementExtractionError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Could not extract statement: {exc}",
        ) from exc
    return _to_response(result)
