"""Accounting period endpoints.

Company-scoped, RBAC-enforced: read = any member, create/transition =
accountant+ (locking protects posted records, so it is privileged). Status
transitions are validated by the engine's period state machine.
"""

from __future__ import annotations

import datetime as dt
import uuid

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from ledgerline_backend.api.membership_deps import AccountantMembership, ReadMembership
from ledgerline_backend.dependencies import CurrentUserDep, SessionDep
from ledgerline_backend.services.period_service import (
    InvalidPeriodError,
    PeriodNotFoundError,
    PeriodOverlapError,
    PeriodService,
)

router = APIRouter(prefix="/companies/{company_id}/periods", tags=["periods"])


_VALID_TARGETS = {"open", "soft_closed", "locked"}


class CreatePeriodRequest(BaseModel):
    fiscal_year: int = Field(ge=1900, le=3000)
    starts_on: dt.date
    ends_on: dt.date


class SetStatusRequest(BaseModel):
    status: str


class PeriodResponse(BaseModel):
    id: uuid.UUID
    fiscal_year: int
    starts_on: dt.date
    ends_on: dt.date
    status: str


@router.get("", response_model=list[PeriodResponse])
def list_periods(
    company_id: uuid.UUID,
    membership: ReadMembership,
    session: SessionDep,
) -> list[PeriodResponse]:
    periods = PeriodService(session).list_periods(company_id)
    return [
        PeriodResponse(
            id=p.id,
            fiscal_year=p.fiscal_year,
            starts_on=p.starts_on,
            ends_on=p.ends_on,
            status=p.status,
        )
        for p in periods
    ]


@router.post("", response_model=PeriodResponse, status_code=status.HTTP_201_CREATED)
def create_period(
    company_id: uuid.UUID,
    body: CreatePeriodRequest,
    current_user: CurrentUserDep,
    membership: AccountantMembership,
    session: SessionDep,
) -> PeriodResponse:
    try:
        period = PeriodService(session).create(
            actor_id=current_user.id,
            company_id=company_id,
            fiscal_year=body.fiscal_year,
            starts_on=body.starts_on,
            ends_on=body.ends_on,
        )
    except (InvalidPeriodError, PeriodOverlapError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return PeriodResponse(
        id=period.id,
        fiscal_year=period.fiscal_year,
        starts_on=period.starts_on,
        ends_on=period.ends_on,
        status=period.status,
    )


@router.post("/{period_id}/status", response_model=PeriodResponse)
def set_period_status(
    company_id: uuid.UUID,
    period_id: uuid.UUID,
    body: SetStatusRequest,
    current_user: CurrentUserDep,
    membership: AccountantMembership,
    session: SessionDep,
) -> PeriodResponse:
    if body.status not in _VALID_TARGETS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown status {body.status!r}",
        )
    try:
        period = PeriodService(session).set_status(
            actor_id=current_user.id,
            company_id=company_id,
            period_id=period_id,
            target=body.status,
        )
    except PeriodNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Period not found"
        ) from exc
    except InvalidPeriodError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return PeriodResponse(
        id=period.id,
        fiscal_year=period.fiscal_year,
        starts_on=period.starts_on,
        ends_on=period.ends_on,
        status=period.status,
    )
