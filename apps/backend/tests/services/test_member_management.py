"""Tests for company member management in CompanyService."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, StaticPool, create_engine, select
from sqlalchemy.orm import Session

from ledgerline_backend import models  # noqa: F401 — register models
from ledgerline_backend.db.base import Base
from ledgerline_backend.models import Organisation, User
from ledgerline_backend.models.membership import (
    ROLE_BOOKKEEPER,
    ROLE_OWNER,
    ROLE_READONLY,
)
from ledgerline_backend.services.company_service import (
    CompanyService,
    InvalidRoleError,
    LastOwnerError,
    MemberNotFoundError,
)


@pytest.fixture
def session() -> Iterator[Session]:
    eng: Engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(eng)
    with Session(eng) as db:
        yield db
    eng.dispose()


def _user(session: Session, email: str) -> User:
    org = session.scalar(select(Organisation))
    if org is None:
        org = Organisation(name="Org", kind="business")
        session.add(org)
        session.flush()
    u = User(org_id=org.id, email=email, display_name=email.split("@")[0], status="active")
    session.add(u)
    session.flush()
    return u


def test_add_member_creates_membership(session: Session) -> None:
    owner = _user(session, "owner@example.com")
    invitee = _user(session, "bk@example.com")
    service = CompanyService(session)
    company = service.create(user=owner, name="Co").company
    session.commit()

    member = service.add_member(
        actor=owner, company_id=company.id, email="bk@example.com", role=ROLE_BOOKKEEPER
    )
    session.commit()

    assert member.user_id == invitee.id
    assert member.role == ROLE_BOOKKEEPER
    rows = service.list_members(company.id)
    assert {m.email for m in rows} == {"owner@example.com", "bk@example.com"}


def test_add_member_unknown_email_raises(session: Session) -> None:
    owner = _user(session, "owner@example.com")
    service = CompanyService(session)
    company = service.create(user=owner, name="Co").company
    session.commit()
    with pytest.raises(MemberNotFoundError):
        service.add_member(
            actor=owner, company_id=company.id, email="ghost@example.com", role=ROLE_READONLY
        )


def test_add_member_invalid_role_raises(session: Session) -> None:
    owner = _user(session, "owner@example.com")
    _user(session, "x@example.com")
    service = CompanyService(session)
    company = service.create(user=owner, name="Co").company
    session.commit()
    with pytest.raises(InvalidRoleError):
        service.add_member(actor=owner, company_id=company.id, email="x@example.com", role="boss")


def test_add_existing_member_updates_role(session: Session) -> None:
    owner = _user(session, "owner@example.com")
    _user(session, "x@example.com")
    service = CompanyService(session)
    company = service.create(user=owner, name="Co").company
    service.add_member(actor=owner, company_id=company.id, email="x@example.com", role=ROLE_READONLY)
    session.commit()

    updated = service.add_member(
        actor=owner, company_id=company.id, email="x@example.com", role=ROLE_BOOKKEEPER
    )
    session.commit()
    assert updated.role == ROLE_BOOKKEEPER
    # Still only two members (owner + x), not three.
    assert len(service.list_members(company.id)) == 2


def test_update_member_role(session: Session) -> None:
    owner = _user(session, "owner@example.com")
    member = _user(session, "m@example.com")
    service = CompanyService(session)
    company = service.create(user=owner, name="Co").company
    service.add_member(actor=owner, company_id=company.id, email="m@example.com", role=ROLE_READONLY)
    session.commit()

    result = service.update_member_role(
        actor=owner, company_id=company.id, target_user_id=member.id, role=ROLE_BOOKKEEPER
    )
    session.commit()
    assert result.role == ROLE_BOOKKEEPER


def test_cannot_demote_last_owner(session: Session) -> None:
    owner = _user(session, "owner@example.com")
    service = CompanyService(session)
    company = service.create(user=owner, name="Co").company
    session.commit()
    with pytest.raises(LastOwnerError):
        service.update_member_role(
            actor=owner, company_id=company.id, target_user_id=owner.id, role=ROLE_READONLY
        )


def test_can_demote_owner_when_another_owner_exists(session: Session) -> None:
    owner = _user(session, "owner@example.com")
    second = _user(session, "owner2@example.com")
    service = CompanyService(session)
    company = service.create(user=owner, name="Co").company
    service.add_member(actor=owner, company_id=company.id, email="owner2@example.com", role=ROLE_OWNER)
    session.commit()

    # Now demoting the first owner is allowed.
    result = service.update_member_role(
        actor=second, company_id=company.id, target_user_id=owner.id, role=ROLE_READONLY
    )
    session.commit()
    assert result.role == ROLE_READONLY


def test_remove_member(session: Session) -> None:
    owner = _user(session, "owner@example.com")
    member = _user(session, "m@example.com")
    service = CompanyService(session)
    company = service.create(user=owner, name="Co").company
    service.add_member(actor=owner, company_id=company.id, email="m@example.com", role=ROLE_READONLY)
    session.commit()

    service.remove_member(actor=owner, company_id=company.id, target_user_id=member.id)
    session.commit()
    assert len(service.list_members(company.id)) == 1


def test_cannot_remove_last_owner(session: Session) -> None:
    owner = _user(session, "owner@example.com")
    service = CompanyService(session)
    company = service.create(user=owner, name="Co").company
    session.commit()
    with pytest.raises(LastOwnerError):
        service.remove_member(actor=owner, company_id=company.id, target_user_id=owner.id)


def test_member_actions_are_audited(session: Session) -> None:
    from ledgerline_backend.models import AuditLog

    owner = _user(session, "owner@example.com")
    _user(session, "m@example.com")
    service = CompanyService(session)
    company = service.create(user=owner, name="Co").company
    service.add_member(actor=owner, company_id=company.id, email="m@example.com", role=ROLE_READONLY)
    session.commit()

    actions = set(
        session.scalars(
            select(AuditLog.action).where(AuditLog.entity_type == "company_membership")
        ).all()
    )
    assert "member_added" in actions
