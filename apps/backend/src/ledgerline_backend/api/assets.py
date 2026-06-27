"""Fixed-asset register endpoints.

Company-scoped, RBAC-enforced: read = any member; create and run-depreciation =
bookkeeper+ (running posts a journal). Depreciation maths is the engine's.
"""

from __future__ import annotations

import datetime as dt
import uuid

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from ledgerline_backend.api.membership_deps import ReadMembership, WriteMembership
from ledgerline_backend.dependencies import CurrentUserDep, SessionDep
from ledgerline_backend.services.asset_service import (
    AssetNotFoundError,
    AssetService,
    AssetView,
    GLAccountInvalidError,
    InvalidAssetError,
)

router = APIRouter(prefix="/companies/{company_id}/fixed-assets", tags=["fixed-assets"])

_METHODS = {"straight_line", "reducing_balance"}


class CreateAssetRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    acquired_on: dt.date
    cost_minor: int = Field(ge=0)
    residual_minor: int = Field(ge=0, default=0)
    method: str
    useful_life_periods: int | None = Field(default=None, ge=1)
    rate_percent: float | None = Field(default=None, gt=0, le=100)
    asset_account_id: uuid.UUID
    accumulated_account_id: uuid.UUID
    expense_account_id: uuid.UUID
    category: str | None = Field(default=None, max_length=64)


class RunDepreciationRequest(BaseModel):
    on_date: dt.date


class AssetResponse(BaseModel):
    id: uuid.UUID
    name: str
    category: str | None
    acquired_on: dt.date
    cost_minor: int
    residual_minor: int
    method: str
    useful_life_periods: int | None
    rate_percent: float | None
    accumulated_depreciation_minor: int
    net_book_value_minor: int
    periods_depreciated: int
    disposed: bool


class DepreciationRunResponse(BaseModel):
    asset_id: uuid.UUID
    charge_minor: int
    journal_id: uuid.UUID | None


def _asset_response(v: AssetView) -> AssetResponse:
    return AssetResponse(
        id=v.id,
        name=v.name,
        category=v.category,
        acquired_on=v.acquired_on,
        cost_minor=v.cost_minor,
        residual_minor=v.residual_minor,
        method=v.method,
        useful_life_periods=v.useful_life_periods,
        rate_percent=v.rate_percent,
        accumulated_depreciation_minor=v.accumulated_depreciation_minor,
        net_book_value_minor=v.net_book_value_minor,
        periods_depreciated=v.periods_depreciated,
        disposed=v.disposed,
    )


@router.get("", response_model=list[AssetResponse])
def list_assets(
    company_id: uuid.UUID,
    membership: ReadMembership,
    session: SessionDep,
) -> list[AssetResponse]:
    """The fixed-asset register with net book value."""
    return [_asset_response(a) for a in AssetService(session).list_assets(company_id)]


@router.post("", response_model=AssetResponse, status_code=status.HTTP_201_CREATED)
def create_asset(
    company_id: uuid.UUID,
    body: CreateAssetRequest,
    current_user: CurrentUserDep,
    membership: WriteMembership,
    session: SessionDep,
) -> AssetResponse:
    """Register a fixed asset (bookkeeper+)."""
    if body.method not in _METHODS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown depreciation method {body.method!r}",
        )
    try:
        asset = AssetService(session).create(
            actor_id=current_user.id,
            company_id=company_id,
            name=body.name,
            acquired_on=body.acquired_on,
            cost_minor=body.cost_minor,
            residual_minor=body.residual_minor,
            method=body.method,
            useful_life_periods=body.useful_life_periods,
            rate_percent=body.rate_percent,
            asset_account_id=body.asset_account_id,
            accumulated_account_id=body.accumulated_account_id,
            expense_account_id=body.expense_account_id,
            category=body.category,
        )
    except GLAccountInvalidError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A chosen general-ledger account is invalid",
        ) from exc
    except InvalidAssetError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return _asset_response(asset)


@router.post("/{asset_id}/depreciate", response_model=DepreciationRunResponse)
def run_depreciation(
    company_id: uuid.UUID,
    asset_id: uuid.UUID,
    body: RunDepreciationRequest,
    current_user: CurrentUserDep,
    membership: WriteMembership,
    session: SessionDep,
) -> DepreciationRunResponse:
    """Depreciate the asset by one period, posting the charge as a journal."""
    try:
        result = AssetService(session).run_depreciation(
            actor_id=current_user.id,
            company_id=company_id,
            asset_id=asset_id,
            on_date=body.on_date,
        )
    except AssetNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found"
        ) from exc
    except InvalidAssetError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return DepreciationRunResponse(
        asset_id=result.asset_id,
        charge_minor=result.charge_minor,
        journal_id=result.journal_id,
    )
