"""Company provisioning and access service.

Encapsulates creating, listing, reading, and updating companies, scoped by
per-company membership (RBAC). A user only ever sees companies they belong to;
their role bounds what they may change. Every mutation writes an audit entry.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Final

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ledgerline_backend.models import Company, CompanyMembership, User
from ledgerline_backend.models.membership import (
    ALL_ROLES,
    ROLE_ACCOUNTANT,
    ROLE_OWNER,
    role_at_least,
)
from ledgerline_backend.services.audit import record_audit

VALID_ACCOUNTS_TYPES: Final = frozenset(
    {"sole_trader", "partnership", "ltd", "micro", "small"}
)


class CompanyError(Exception):
    """Base class for company-related failures."""


class CompanyNotFoundError(CompanyError):
    """The company does not exist, or the user is not a member (leak-safe)."""


class CompanyAccessDeniedError(CompanyError):
    """The user's role does not permit the requested action."""


class InvalidCompanyError(CompanyError):
    """The company data is invalid (e.g. unknown accounts type)."""


class InvalidRoleError(CompanyError):
    """An unknown membership role was supplied."""


class MemberNotFoundError(CompanyError):
    """The target user is not a member of the company (or does not exist)."""


class LastOwnerError(CompanyError):
    """The action would leave the company without an owner."""


@dataclass(frozen=True)
class CompanyWithRole:
    """A company paired with the requesting user's role in it."""

    company: Company
    role: str


@dataclass(frozen=True)
class MemberView:
    """A company member: the membership plus the user's identity fields."""

    user_id: uuid.UUID
    email: str
    display_name: str
    role: str


class CompanyService:
    """Company provisioning and access, scoped by membership."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def _membership(self, user_id: uuid.UUID, company_id: uuid.UUID) -> CompanyMembership | None:
        return self._session.scalar(
            select(CompanyMembership).where(
                CompanyMembership.user_id == user_id,
                CompanyMembership.company_id == company_id,
            )
        )

    def create(
        self,
        *,
        user: User,
        name: str,
        base_currency: str = "GBP",
        accounts_type: str = "ltd",
    ) -> CompanyWithRole:
        """Create a company under the user's organisation and make them owner."""
        if accounts_type not in VALID_ACCOUNTS_TYPES:
            raise InvalidCompanyError
        if not name.strip():
            raise InvalidCompanyError

        company = Company(
            org_id=user.org_id,
            name=name.strip(),
            base_currency=base_currency,
            accounts_type=accounts_type,
        )
        self._session.add(company)
        self._session.flush()

        membership = CompanyMembership(
            user_id=user.id, company_id=company.id, role=ROLE_OWNER
        )
        self._session.add(membership)
        self._session.flush()

        record_audit(
            self._session,
            entity_type="company",
            entity_id=company.id,
            action="created",
            actor_user_id=user.id,
            company_id=company.id,
        )
        return CompanyWithRole(company=company, role=ROLE_OWNER)

    def list_for_user(self, user_id: uuid.UUID) -> list[CompanyWithRole]:
        """Return companies the user is a member of, with their role."""
        rows = self._session.execute(
            select(Company, CompanyMembership.role)
            .join(CompanyMembership, CompanyMembership.company_id == Company.id)
            .where(CompanyMembership.user_id == user_id, Company.is_deleted.is_(False))
            .order_by(Company.created_at.desc())
        ).all()
        return [CompanyWithRole(company=c, role=r) for c, r in rows]

    def get_for_user(self, user_id: uuid.UUID, company_id: uuid.UUID) -> CompanyWithRole:
        """Return a company the user may access, or raise (leak-safe not-found)."""
        membership = self._membership(user_id, company_id)
        if membership is None:
            raise CompanyNotFoundError
        company = self._session.get(Company, company_id)
        if company is None or company.is_deleted:
            raise CompanyNotFoundError
        return CompanyWithRole(company=company, role=membership.role)

    def update(
        self,
        *,
        user: User,
        company_id: uuid.UUID,
        name: str | None = None,
        accounts_type: str | None = None,
        companies_house_no: str | None = None,
        vat_registration_no: str | None = None,
    ) -> CompanyWithRole:
        """Update mutable company fields. Requires accountant or owner role."""
        membership = self._membership(user.id, company_id)
        if membership is None:
            raise CompanyNotFoundError
        if not role_at_least(membership.role, ROLE_ACCOUNTANT):
            raise CompanyAccessDeniedError

        company = self._session.get(Company, company_id)
        if company is None or company.is_deleted:
            raise CompanyNotFoundError

        if name is not None:
            if not name.strip():
                raise InvalidCompanyError
            company.name = name.strip()
        if accounts_type is not None:
            if accounts_type not in VALID_ACCOUNTS_TYPES:
                raise InvalidCompanyError
            company.accounts_type = accounts_type
        if companies_house_no is not None:
            company.companies_house_no = companies_house_no or None
        if vat_registration_no is not None:
            company.vat_registration_no = vat_registration_no or None

        company.version += 1
        record_audit(
            self._session,
            entity_type="company",
            entity_id=company.id,
            action="updated",
            actor_user_id=user.id,
            company_id=company.id,
        )
        return CompanyWithRole(company=company, role=membership.role)

    @staticmethod
    def is_valid_role(role: str) -> bool:
        return role in ALL_ROLES

    # -- member management (owner-only) -----------------------------------

    def list_members(self, company_id: uuid.UUID) -> list[MemberView]:
        """List all members of a company with their identity and role."""
        rows = self._session.execute(
            select(User, CompanyMembership.role)
            .join(CompanyMembership, CompanyMembership.user_id == User.id)
            .where(CompanyMembership.company_id == company_id)
            .order_by(User.email)
        ).all()
        return [
            MemberView(user_id=u.id, email=u.email, display_name=u.display_name, role=r)
            for u, r in rows
        ]

    def add_member(
        self, *, actor: User, company_id: uuid.UUID, email: str, role: str
    ) -> MemberView:
        """Add an existing user (by email) to the company with a role.

        Idempotent on role: if the user is already a member, their role is
        updated. The actor must be an owner (enforced by the route dependency).
        """
        if role not in ALL_ROLES:
            raise InvalidRoleError
        normalized = email.strip().lower()
        target = self._session.scalar(select(User).where(User.email == normalized))
        if target is None:
            raise MemberNotFoundError

        existing = self._membership(target.id, company_id)
        if existing is not None:
            existing.role = role
            action = "member_role_changed"
        else:
            self._session.add(
                CompanyMembership(user_id=target.id, company_id=company_id, role=role)
            )
            action = "member_added"
        self._session.flush()
        record_audit(
            self._session,
            entity_type="company_membership",
            entity_id=target.id,
            action=action,
            actor_user_id=actor.id,
            company_id=company_id,
            reason=f"role={role}",
        )
        return MemberView(
            user_id=target.id, email=target.email, display_name=target.display_name, role=role
        )

    def update_member_role(
        self, *, actor: User, company_id: uuid.UUID, target_user_id: uuid.UUID, role: str
    ) -> MemberView:
        """Change a member's role, preventing removal of the last owner."""
        if role not in ALL_ROLES:
            raise InvalidRoleError
        membership = self._membership(target_user_id, company_id)
        if membership is None:
            raise MemberNotFoundError

        if membership.role == ROLE_OWNER and role != ROLE_OWNER:
            self._guard_last_owner(company_id, demoting_user_id=target_user_id)

        membership.role = role
        target = self._session.get(User, target_user_id)
        if target is None:  # pragma: no cover — FK guarantees presence
            raise MemberNotFoundError
        record_audit(
            self._session,
            entity_type="company_membership",
            entity_id=target_user_id,
            action="member_role_changed",
            actor_user_id=actor.id,
            company_id=company_id,
            reason=f"role={role}",
        )
        return MemberView(
            user_id=target.id, email=target.email, display_name=target.display_name, role=role
        )

    def remove_member(
        self, *, actor: User, company_id: uuid.UUID, target_user_id: uuid.UUID
    ) -> None:
        """Remove a member, preventing removal of the last owner."""
        membership = self._membership(target_user_id, company_id)
        if membership is None:
            raise MemberNotFoundError
        if membership.role == ROLE_OWNER:
            self._guard_last_owner(company_id, demoting_user_id=target_user_id)

        self._session.delete(membership)
        record_audit(
            self._session,
            entity_type="company_membership",
            entity_id=target_user_id,
            action="member_removed",
            actor_user_id=actor.id,
            company_id=company_id,
        )

    def _guard_last_owner(self, company_id: uuid.UUID, *, demoting_user_id: uuid.UUID) -> None:
        """Raise if demoting/removing this user would leave no owner."""
        other_owners = self._session.scalar(
            select(func.count())
            .select_from(CompanyMembership)
            .where(
                CompanyMembership.company_id == company_id,
                CompanyMembership.role == ROLE_OWNER,
                CompanyMembership.user_id != demoting_user_id,
            )
        )
        if not other_owners:
            raise LastOwnerError
