"""Chart of Accounts service.

Manages a company's nominal accounts: create, list, update, deactivate. Account
types and their normal-balance side are derived from the canonical accounting
``engine`` so the backend and engine never disagree. All mutations are audited
and scoped to the company (RBAC enforced at the route layer).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from ledgerline_engine.api import AccountType, ControlKind, normal_balance_for
from sqlalchemy import select
from sqlalchemy.orm import Session

from ledgerline_backend.models import ChartOfAccount
from ledgerline_backend.services.audit import record_audit


class CoaError(Exception):
    """Base class for chart-of-accounts failures."""


class InvalidAccountError(CoaError):
    """The account data is invalid (unknown type/control kind, blank code)."""


class DuplicateAccountCodeError(CoaError):
    """An account with that code already exists in the company."""


class AccountNotFoundError(CoaError):
    """No such account in the company."""


# Valid string values, derived from the engine enums (single source of truth).
VALID_ACCOUNT_TYPES = frozenset(t.value for t in AccountType)
VALID_CONTROL_KINDS = frozenset(k.value for k in ControlKind)


@dataclass(frozen=True)
class AccountView:
    """A chart-of-accounts row for presentation."""

    id: uuid.UUID
    code: str
    name: str
    account_type: str
    normal_balance: str
    is_control: bool
    control_kind: str | None
    is_active: bool


def _to_view(account: ChartOfAccount) -> AccountView:
    return AccountView(
        id=account.id,
        code=account.code,
        name=account.name,
        account_type=account.account_type,
        normal_balance=account.normal_balance,
        is_control=account.is_control,
        control_kind=account.control_kind,
        is_active=account.is_active,
    )


class CoaService:
    """Chart-of-accounts use-cases bound to a session."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def _derive_normal_balance(self, account_type: str) -> str:
        """Normal balance side, derived from the engine (DR/CR)."""
        balance: str = normal_balance_for(AccountType(account_type)).value
        return balance

    def create(
        self,
        *,
        actor_id: uuid.UUID,
        company_id: uuid.UUID,
        code: str,
        name: str,
        account_type: str,
        control_kind: str | None = None,
    ) -> AccountView:
        """Create a nominal account. Normal balance is derived from the type."""
        code = code.strip()
        name = name.strip()
        if not code or not name:
            raise InvalidAccountError
        if account_type not in VALID_ACCOUNT_TYPES:
            raise InvalidAccountError
        if control_kind is not None and control_kind not in VALID_CONTROL_KINDS:
            raise InvalidAccountError

        existing = self._session.scalar(
            select(ChartOfAccount).where(
                ChartOfAccount.company_id == company_id,
                ChartOfAccount.code == code,
            )
        )
        if existing is not None:
            raise DuplicateAccountCodeError

        account = ChartOfAccount(
            company_id=company_id,
            code=code,
            name=name,
            account_type=account_type,
            normal_balance=self._derive_normal_balance(account_type),
            is_control=control_kind is not None,
            control_kind=control_kind,
            is_active=True,
        )
        self._session.add(account)
        self._session.flush()
        record_audit(
            self._session,
            entity_type="chart_of_account",
            entity_id=account.id,
            action="created",
            actor_user_id=actor_id,
            company_id=company_id,
            reason=f"code={code}",
        )
        return _to_view(account)

    def list_for_company(
        self, company_id: uuid.UUID, *, include_inactive: bool = True
    ) -> list[AccountView]:
        """List a company's accounts, ordered by code."""
        stmt = select(ChartOfAccount).where(ChartOfAccount.company_id == company_id)
        if not include_inactive:
            stmt = stmt.where(ChartOfAccount.is_active.is_(True))
        stmt = stmt.order_by(ChartOfAccount.code)
        return [_to_view(a) for a in self._session.scalars(stmt).all()]

    def _get(self, company_id: uuid.UUID, account_id: uuid.UUID) -> ChartOfAccount:
        account = self._session.get(ChartOfAccount, account_id)
        if account is None or account.company_id != company_id:
            raise AccountNotFoundError
        return account

    def update(
        self,
        *,
        actor_id: uuid.UUID,
        company_id: uuid.UUID,
        account_id: uuid.UUID,
        name: str | None = None,
    ) -> AccountView:
        """Rename an account. Type/normal-balance are immutable once created
        (changing them would invalidate posted history)."""
        account = self._get(company_id, account_id)
        if name is not None:
            name = name.strip()
            if not name:
                raise InvalidAccountError
            account.name = name
            account.version += 1
        record_audit(
            self._session,
            entity_type="chart_of_account",
            entity_id=account.id,
            action="updated",
            actor_user_id=actor_id,
            company_id=company_id,
        )
        return _to_view(account)

    def set_active(
        self,
        *,
        actor_id: uuid.UUID,
        company_id: uuid.UUID,
        account_id: uuid.UUID,
        is_active: bool,
    ) -> AccountView:
        """Activate or deactivate an account."""
        account = self._get(company_id, account_id)
        account.is_active = is_active
        account.version += 1
        record_audit(
            self._session,
            entity_type="chart_of_account",
            entity_id=account.id,
            action="activated" if is_active else "deactivated",
            actor_user_id=actor_id,
            company_id=company_id,
        )
        return _to_view(account)
