"""Tests for the CompanyService: provisioning, scoping, RBAC, and audit."""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, StaticPool, create_engine, select
from sqlalchemy.orm import Session

from ledgerline_backend import models  # noqa: F401 — register models
from ledgerline_backend.db.base import Base
from ledgerline_backend.models import AuditLog, CompanyMembership, Organisation, User
from ledgerline_backend.models.membership import ROLE_BOOKKEEPER, ROLE_OWNER, ROLE_READONLY
from ledgerline_backend.services.company_service import (
    CompanyAccessDeniedError,
    CompanyNotFoundError,
    CompanyService,
    InvalidCompanyError,
)


@pytest.fixture
def engine() -> Iterator[Engine]:
    eng = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(eng)
    try:
        yield eng
    finally:
        eng.dispose()


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    with Session(engine) as db:
        yield db


def _user(session: Session, email: str = "owner@example.com") -> User:
    org = session.scalar(select(Organisation))
    if org is None:
        org = Organisation(name="Org", kind="business")
        session.add(org)
        session.flush()
    u = User(org_id=org.id, email=email, display_name="U", status="active")
    session.add(u)
    session.flush()
    return u


def test_create_company_makes_owner_membership(session: Session) -> None:
    user = _user(session)
    service = CompanyService(session)
    result = service.create(user=user, name="Acme Ltd")
    session.commit()

    assert result.role == ROLE_OWNER
    assert result.company.name == "Acme Ltd"
    assert result.company.org_id == user.org_id

    membership = session.scalar(
        select(CompanyMembership).where(CompanyMembership.company_id == result.company.id)
    )
    assert membership is not None
    assert membership.user_id == user.id
    assert membership.role == ROLE_OWNER


def test_create_writes_audit_entry(session: Session) -> None:
    user = _user(session)
    result = CompanyService(session).create(user=user, name="Acme Ltd")
    session.commit()

    audit = session.scalar(select(AuditLog).where(AuditLog.entity_id == result.company.id))
    assert audit is not None
    assert audit.action == "created"
    assert audit.entity_type == "company"
    assert audit.actor_user_id == user.id
    assert audit.this_hash is not None


def test_create_rejects_invalid_accounts_type(session: Session) -> None:
    user = _user(session)
    with pytest.raises(InvalidCompanyError):
        CompanyService(session).create(user=user, name="X", accounts_type="banana")


def test_create_rejects_blank_name(session: Session) -> None:
    user = _user(session)
    with pytest.raises(InvalidCompanyError):
        CompanyService(session).create(user=user, name="   ")


def test_list_only_returns_users_companies(session: Session) -> None:
    owner = _user(session, "owner@example.com")
    other = _user(session, "other@example.com")
    service = CompanyService(session)
    service.create(user=owner, name="Owner Co")
    service.create(user=other, name="Other Co")
    session.commit()

    owner_companies = service.list_for_user(owner.id)
    assert len(owner_companies) == 1
    assert owner_companies[0].company.name == "Owner Co"
    assert owner_companies[0].role == ROLE_OWNER


def test_get_for_user_rejects_non_member(session: Session) -> None:
    owner = _user(session, "owner@example.com")
    other = _user(session, "other@example.com")
    service = CompanyService(session)
    created = service.create(user=owner, name="Owner Co")
    session.commit()

    with pytest.raises(CompanyNotFoundError):
        service.get_for_user(other.id, created.company.id)


def test_get_unknown_company_raises(session: Session) -> None:
    user = _user(session)
    with pytest.raises(CompanyNotFoundError):
        CompanyService(session).get_for_user(user.id, uuid.uuid4())


def test_update_by_owner_succeeds(session: Session) -> None:
    user = _user(session)
    service = CompanyService(session)
    created = service.create(user=user, name="Old Name")
    session.commit()

    updated = service.update(user=user, company_id=created.company.id, name="New Name")
    session.commit()
    assert updated.company.name == "New Name"
    assert updated.company.version == 2  # bumped on update


def test_update_by_readonly_member_is_denied(session: Session) -> None:
    owner = _user(session, "owner@example.com")
    viewer = _user(session, "viewer@example.com")
    service = CompanyService(session)
    created = service.create(user=owner, name="Co")
    # Add the viewer as a read-only member.
    session.add(
        CompanyMembership(user_id=viewer.id, company_id=created.company.id, role=ROLE_READONLY)
    )
    session.commit()

    with pytest.raises(CompanyAccessDeniedError):
        service.update(user=viewer, company_id=created.company.id, name="Hacked")


def test_update_by_bookkeeper_is_denied(session: Session) -> None:
    owner = _user(session, "owner@example.com")
    bk = _user(session, "bk@example.com")
    service = CompanyService(session)
    created = service.create(user=owner, name="Co")
    session.add(
        CompanyMembership(user_id=bk.id, company_id=created.company.id, role=ROLE_BOOKKEEPER)
    )
    session.commit()

    with pytest.raises(CompanyAccessDeniedError):
        service.update(user=bk, company_id=created.company.id, name="Nope")


def test_update_non_member_is_not_found(session: Session) -> None:
    owner = _user(session, "owner@example.com")
    stranger = _user(session, "stranger@example.com")
    service = CompanyService(session)
    created = service.create(user=owner, name="Co")
    session.commit()

    with pytest.raises(CompanyNotFoundError):
        service.update(user=stranger, company_id=created.company.id, name="Nope")
