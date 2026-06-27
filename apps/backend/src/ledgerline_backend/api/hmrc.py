"""HMRC Making Tax Digital (MTD) for VAT endpoints.

OAuth connection (authorize URL + code exchange), VAT obligations, and submitting
a finalised VAT return to HMRC. Company-scoped, RBAC-enforced: viewing obligations
and connection status = any member; connecting and submitting = accountant+ (these
file with the tax authority). The HMRC client is injected, so this is testable
without live HMRC access.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, Field

from ledgerline_backend.api.membership_deps import AccountantMembership, ReadMembership
from ledgerline_backend.dependencies import (
    CurrentUserDep,
    HmrcClientDep,
    SessionDep,
)
from ledgerline_backend.services.hmrc_client import HttpHmrcClient
from ledgerline_backend.services.mtd_service import (
    AlreadySubmittedError,
    MtdError,
    MtdNotConnectedError,
    MtdNoVrnError,
    MtdService,
    SubmissionNotFoundError,
)

router = APIRouter(prefix="/companies/{company_id}/hmrc", tags=["hmrc-mtd"])


class ConnectionStatusResponse(BaseModel):
    connected: bool


class AuthorizeUrlResponse(BaseModel):
    authorize_url: str


class ExchangeCodeRequest(BaseModel):
    code: str = Field(min_length=1)


class ObligationResponse(BaseModel):
    period_key: str
    start: str
    end: str
    due: str
    status: str
    received: str | None


class SubmitRequest(BaseModel):
    submission_id: uuid.UUID
    period_key: str = Field(min_length=1)


class SubmitResponse(BaseModel):
    submission_id: uuid.UUID
    form_bundle_number: str
    charge_ref_number: str | None
    received_at: str


@router.get("/status", response_model=ConnectionStatusResponse)
def connection_status(
    company_id: uuid.UUID,
    membership: ReadMembership,
    session: SessionDep,
    client: HmrcClientDep,
) -> ConnectionStatusResponse:
    """Whether this company has a stored HMRC token."""
    connected = MtdService(session, client).is_connected(company_id)
    return ConnectionStatusResponse(connected=connected)


@router.get("/authorize-url", response_model=AuthorizeUrlResponse)
def authorize_url(
    company_id: uuid.UUID,
    membership: AccountantMembership,
    client: HmrcClientDep,
) -> AuthorizeUrlResponse:
    """The HMRC consent URL to redirect the user to (accountant+)."""
    if not isinstance(client, HttpHmrcClient):  # pragma: no cover - only in tests
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="HMRC MTD is not configured",
        )
    # The company id rides in state so the callback can attribute the token.
    return AuthorizeUrlResponse(authorize_url=client.authorize_url(state=str(company_id)))


@router.post("/exchange", status_code=status.HTTP_204_NO_CONTENT)
def exchange_code(
    company_id: uuid.UUID,
    body: ExchangeCodeRequest,
    current_user: CurrentUserDep,
    membership: AccountantMembership,
    session: SessionDep,
    client: HmrcClientDep,
) -> Response:
    """Exchange an OAuth authorization code for a token and store it (accountant+)."""
    try:
        MtdService(session, client).exchange_and_store(company_id=company_id, code=body.code)
    except MtdError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/obligations", response_model=list[ObligationResponse])
def obligations(
    company_id: uuid.UUID,
    from_date: str,
    to_date: str,
    membership: ReadMembership,
    session: SessionDep,
    client: HmrcClientDep,
) -> list[ObligationResponse]:
    """List the company's VAT obligations from HMRC for a date range."""
    try:
        items = MtdService(session, client).obligations(
            company_id, from_date=from_date, to_date=to_date
        )
    except MtdNotConnectedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except MtdNoVrnError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except MtdError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return [
        ObligationResponse(
            period_key=o.period_key,
            start=o.start,
            end=o.end,
            due=o.due,
            status=o.status,
            received=o.received,
        )
        for o in items
    ]


@router.post("/submit", response_model=SubmitResponse)
def submit_to_hmrc(
    company_id: uuid.UUID,
    body: SubmitRequest,
    current_user: CurrentUserDep,
    membership: AccountantMembership,
    session: SessionDep,
    client: HmrcClientDep,
) -> SubmitResponse:
    """Submit a finalised VAT return to HMRC and store the receipt (accountant+)."""
    try:
        result = MtdService(session, client).submit_to_hmrc(
            actor_id=current_user.id,
            company_id=company_id,
            submission_id=body.submission_id,
            period_key=body.period_key,
        )
    except SubmissionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="VAT submission not found"
        ) from exc
    except AlreadySubmittedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except (MtdNotConnectedError, MtdNoVrnError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except MtdError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return SubmitResponse(
        submission_id=result.submission_id,
        form_bundle_number=result.form_bundle_number,
        charge_ref_number=result.charge_ref_number,
        received_at=result.received_at.isoformat(),
    )
