"""Chart of Accounts endpoints (company-scoped, RBAC-enforced).

Reading requires membership (any role); creating/editing requires at least the
bookkeeper role. All routes are nested under a company and use the reusable
RBAC dependency to resolve and authorise the caller's membership.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from ledgerline_backend.api.membership_deps import ReadMembership, WriteMembership
from ledgerline_backend.dependencies import CurrentUserDep, SessionDep
from ledgerline_backend.services.coa_service import (
    AccountNotFoundError,
    AccountView,
    CoaService,
    DuplicateAccountCodeError,
    InvalidAccountError,
)

router = APIRouter(prefix="/companies/{company_id}/accounts", tags=["chart-of-accounts"])


class CreateAccountRequest(BaseModel):
    code: str = Field(min_length=1, max_length=16)
    name: str = Field(min_length=1, max_length=255)
    account_type: str = Field(max_length=16)
    control_kind: str | None = Field(default=None, max_length=16)


class UpdateAccountRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class AccountResponse(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    account_type: str
    normal_balance: str
    is_control: bool
    control_kind: str | None
    is_active: bool


def _to_response(v: AccountView) -> AccountResponse:
    return AccountResponse(
        id=v.id,
        code=v.code,
        name=v.name,
        account_type=v.account_type,
        normal_balance=v.normal_balance,
        is_control=v.is_control,
        control_kind=v.control_kind,
        is_active=v.is_active,
    )


@router.get("", response_model=list[AccountResponse])
def list_accounts(
    company_id: uuid.UUID,
    membership: ReadMembership,
    session: SessionDep,
    include_inactive: bool = True,
) -> list[AccountResponse]:
    """List the company's chart of accounts."""
    accounts = CoaService(session).list_for_company(
        company_id, include_inactive=include_inactive
    )
    return [_to_response(a) for a in accounts]


@router.post("", response_model=AccountResponse, status_code=status.HTTP_201_CREATED)
def create_account(
    company_id: uuid.UUID,
    body: CreateAccountRequest,
    current_user: CurrentUserDep,
    membership: WriteMembership,
    session: SessionDep,
) -> AccountResponse:
    """Create a nominal account (bookkeeper or higher)."""
    try:
        account = CoaService(session).create(
            actor_id=current_user.id,
            company_id=company_id,
            code=body.code,
            name=body.name,
            account_type=body.account_type,
            control_kind=body.control_kind,
        )
    except DuplicateAccountCodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with that code already exists",
        ) from exc
    except InvalidAccountError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid account details",
        ) from exc
    return _to_response(account)


@router.patch("/{account_id}", response_model=AccountResponse)
def update_account(
    company_id: uuid.UUID,
    account_id: uuid.UUID,
    body: UpdateAccountRequest,
    current_user: CurrentUserDep,
    membership: WriteMembership,
    session: SessionDep,
) -> AccountResponse:
    """Rename an account (bookkeeper or higher)."""
    try:
        account = CoaService(session).update(
            actor_id=current_user.id,
            company_id=company_id,
            account_id=account_id,
            name=body.name,
        )
    except AccountNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Account not found"
        ) from exc
    except InvalidAccountError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid account details",
        ) from exc
    return _to_response(account)


@router.post("/{account_id}/deactivate", response_model=AccountResponse)
def deactivate_account(
    company_id: uuid.UUID,
    account_id: uuid.UUID,
    current_user: CurrentUserDep,
    membership: WriteMembership,
    session: SessionDep,
) -> AccountResponse:
    """Deactivate an account so it can no longer be posted to."""
    try:
        account = CoaService(session).set_active(
            actor_id=current_user.id,
            company_id=company_id,
            account_id=account_id,
            is_active=False,
        )
    except AccountNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Account not found"
        ) from exc
    return _to_response(account)


@router.post("/{account_id}/activate", response_model=AccountResponse)
def activate_account(
    company_id: uuid.UUID,
    account_id: uuid.UUID,
    current_user: CurrentUserDep,
    membership: WriteMembership,
    session: SessionDep,
) -> AccountResponse:
    """Reactivate a previously-deactivated account."""
    try:
        account = CoaService(session).set_active(
            actor_id=current_user.id,
            company_id=company_id,
            account_id=account_id,
            is_active=True,
        )
    except AccountNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Account not found"
        ) from exc
    return _to_response(account)
