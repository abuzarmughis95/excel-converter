"""Company provisioning and access endpoints.

All routes are scoped to the authenticated user's memberships: a user can only
list, read, or modify companies they belong to, and their role bounds writes.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, EmailStr, Field

from ledgerline_backend.api.membership_deps import OwnerMembership
from ledgerline_backend.dependencies import CurrentUserDep, SessionDep
from ledgerline_backend.services.company_service import (
    CompanyAccessDeniedError,
    CompanyNotFoundError,
    CompanyService,
    CompanyWithRole,
    InvalidCompanyError,
    InvalidRoleError,
    LastOwnerError,
    MemberNotFoundError,
    MemberView,
)

router = APIRouter(prefix="/companies", tags=["companies"])

# Owner-only dependency for member-management routes.


class CreateCompanyRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    base_currency: str = Field(default="GBP", min_length=3, max_length=3)
    accounts_type: str = Field(default="ltd", max_length=32)


class UpdateCompanyRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    accounts_type: str | None = Field(default=None, max_length=32)
    companies_house_no: str | None = Field(default=None, max_length=16)
    vat_registration_no: str | None = Field(default=None, max_length=16)


class CompanyResponse(BaseModel):
    id: uuid.UUID
    name: str
    base_currency: str
    accounts_type: str
    companies_house_no: str | None
    vat_registration_no: str | None
    role: str


def _to_response(cw: CompanyWithRole) -> CompanyResponse:
    c = cw.company
    return CompanyResponse(
        id=c.id,
        name=c.name,
        base_currency=c.base_currency,
        accounts_type=c.accounts_type,
        companies_house_no=c.companies_house_no,
        vat_registration_no=c.vat_registration_no,
        role=cw.role,
    )


@router.post("", response_model=CompanyResponse, status_code=status.HTTP_201_CREATED)
def create_company(
    body: CreateCompanyRequest, current_user: CurrentUserDep, session: SessionDep
) -> CompanyResponse:
    """Create a company; the caller becomes its owner."""
    try:
        created = CompanyService(session).create(
            user=current_user,
            name=body.name,
            base_currency=body.base_currency.upper(),
            accounts_type=body.accounts_type,
        )
    except InvalidCompanyError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid company details",
        ) from exc
    return _to_response(created)


@router.get("", response_model=list[CompanyResponse])
def list_companies(current_user: CurrentUserDep, session: SessionDep) -> list[CompanyResponse]:
    """List the companies the authenticated user belongs to."""
    return [_to_response(cw) for cw in CompanyService(session).list_for_user(current_user.id)]


@router.get("/{company_id}", response_model=CompanyResponse)
def get_company(
    company_id: uuid.UUID, current_user: CurrentUserDep, session: SessionDep
) -> CompanyResponse:
    """Read a single company the user may access."""
    try:
        return _to_response(CompanyService(session).get_for_user(current_user.id, company_id))
    except CompanyNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Company not found"
        ) from exc


@router.patch("/{company_id}", response_model=CompanyResponse)
def update_company(
    company_id: uuid.UUID,
    body: UpdateCompanyRequest,
    current_user: CurrentUserDep,
    session: SessionDep,
) -> CompanyResponse:
    """Update a company (requires accountant or owner role)."""
    service = CompanyService(session)
    try:
        updated = service.update(
            user=current_user,
            company_id=company_id,
            name=body.name,
            accounts_type=body.accounts_type,
            companies_house_no=body.companies_house_no,
            vat_registration_no=body.vat_registration_no,
        )
    except CompanyNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Company not found"
        ) from exc
    except CompanyAccessDeniedError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your role does not permit this action",
        ) from exc
    except InvalidCompanyError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid company details",
        ) from exc
    return _to_response(updated)


# -- member management (owner-only) ---------------------------------------


class MemberResponse(BaseModel):
    user_id: uuid.UUID
    email: EmailStr
    display_name: str
    role: str


class AddMemberRequest(BaseModel):
    email: EmailStr
    role: str = Field(max_length=16)


class UpdateMemberRoleRequest(BaseModel):
    role: str = Field(max_length=16)


def _member_response(m: MemberView) -> MemberResponse:
    return MemberResponse(
        user_id=m.user_id, email=m.email, display_name=m.display_name, role=m.role
    )


@router.get("/{company_id}/members", response_model=list[MemberResponse])
def list_members(
    company_id: uuid.UUID,
    membership: OwnerMembership,
    session: SessionDep,
) -> list[MemberResponse]:
    """List a company's members (owner only)."""
    return [_member_response(m) for m in CompanyService(session).list_members(company_id)]


@router.post(
    "/{company_id}/members", response_model=MemberResponse, status_code=status.HTTP_201_CREATED
)
def add_member(
    company_id: uuid.UUID,
    body: AddMemberRequest,
    current_user: CurrentUserDep,
    membership: OwnerMembership,
    session: SessionDep,
) -> MemberResponse:
    """Add an existing user (by email) to the company (owner only)."""
    try:
        member = CompanyService(session).add_member(
            actor=current_user, company_id=company_id, email=str(body.email), role=body.role
        )
    except InvalidRoleError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unknown role"
        ) from exc
    except MemberNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No user with that email"
        ) from exc
    return _member_response(member)


@router.patch("/{company_id}/members/{user_id}", response_model=MemberResponse)
def update_member_role(
    company_id: uuid.UUID,
    user_id: uuid.UUID,
    body: UpdateMemberRoleRequest,
    current_user: CurrentUserDep,
    membership: OwnerMembership,
    session: SessionDep,
) -> MemberResponse:
    """Change a member's role (owner only). Cannot demote the last owner."""
    try:
        member = CompanyService(session).update_member_role(
            actor=current_user, company_id=company_id, target_user_id=user_id, role=body.role
        )
    except InvalidRoleError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unknown role"
        ) from exc
    except MemberNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Member not found"
        ) from exc
    except LastOwnerError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot remove the last owner",
        ) from exc
    return _member_response(member)


@router.delete("/{company_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(
    company_id: uuid.UUID,
    user_id: uuid.UUID,
    current_user: CurrentUserDep,
    membership: OwnerMembership,
    session: SessionDep,
) -> Response:
    """Remove a member from the company (owner only). Cannot remove last owner."""
    try:
        CompanyService(session).remove_member(
            actor=current_user, company_id=company_id, target_user_id=user_id
        )
    except MemberNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Member not found"
        ) from exc
    except LastOwnerError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot remove the last owner",
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
