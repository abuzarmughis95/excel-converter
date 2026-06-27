"""Tests for the Chart of Accounts service."""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, StaticPool, create_engine, select
from sqlalchemy.orm import Session

from ledgerline_backend import models  # noqa: F401 — register models
from ledgerline_backend.db.base import Base
from ledgerline_backend.models import AuditLog, ChartOfAccount, Company, Organisation, User
from ledgerline_backend.services.coa_service import (
    AccountNotFoundError,
    CoaService,
    DuplicateAccountCodeError,
    InvalidAccountError,
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


@pytest.fixture
def company(session: Session) -> Company:
    org = Organisation(name="Org", kind="business")
    session.add(org)
    session.flush()
    user = User(org_id=org.id, email="u@example.com", display_name="U", status="active")
    session.add(user)
    co = Company(org_id=org.id, name="Co", accounts_type="ltd")
    session.add(co)
    session.commit()
    return co


@pytest.fixture
def actor_id(session: Session) -> uuid.UUID:
    return session.scalar(select(User.id))  # type: ignore[return-value]


def test_create_derives_normal_balance_from_engine(
    session: Session, company: Company, actor_id: uuid.UUID
) -> None:
    svc = CoaService(session)
    bank = svc.create(
        actor_id=actor_id, company_id=company.id, code="1200", name="Bank", account_type="asset"
    )
    sales = svc.create(
        actor_id=actor_id, company_id=company.id, code="4000", name="Sales", account_type="income"
    )
    session.commit()
    # Assets are debit-normal; income is credit-normal (derived from the engine).
    assert bank.normal_balance == "DR"
    assert sales.normal_balance == "CR"


def test_create_control_account(
    session: Session, company: Company, actor_id: uuid.UUID
) -> None:
    svc = CoaService(session)
    vat = svc.create(
        actor_id=actor_id,
        company_id=company.id,
        code="2200",
        name="VAT",
        account_type="liability",
        control_kind="vat",
    )
    session.commit()
    assert vat.is_control is True
    assert vat.control_kind == "vat"
    assert vat.normal_balance == "CR"


def test_create_rejects_unknown_type(
    session: Session, company: Company, actor_id: uuid.UUID
) -> None:
    with pytest.raises(InvalidAccountError):
        CoaService(session).create(
            actor_id=actor_id, company_id=company.id, code="9", name="X", account_type="banana"
        )


def test_create_rejects_unknown_control_kind(
    session: Session, company: Company, actor_id: uuid.UUID
) -> None:
    with pytest.raises(InvalidAccountError):
        CoaService(session).create(
            actor_id=actor_id,
            company_id=company.id,
            code="9",
            name="X",
            account_type="asset",
            control_kind="nonsense",
        )


def test_create_rejects_blank_code(
    session: Session, company: Company, actor_id: uuid.UUID
) -> None:
    with pytest.raises(InvalidAccountError):
        CoaService(session).create(
            actor_id=actor_id, company_id=company.id, code="   ", name="X", account_type="asset"
        )


def test_duplicate_code_rejected(
    session: Session, company: Company, actor_id: uuid.UUID
) -> None:
    svc = CoaService(session)
    svc.create(
        actor_id=actor_id, company_id=company.id, code="1200", name="Bank", account_type="asset"
    )
    session.commit()
    with pytest.raises(DuplicateAccountCodeError):
        svc.create(
            actor_id=actor_id,
            company_id=company.id,
            code="1200",
            name="Bank 2",
            account_type="asset",
        )


def test_list_ordered_by_code(
    session: Session, company: Company, actor_id: uuid.UUID
) -> None:
    svc = CoaService(session)
    svc.create(actor_id=actor_id, company_id=company.id, code="4000", name="Sales", account_type="income")
    svc.create(actor_id=actor_id, company_id=company.id, code="1200", name="Bank", account_type="asset")
    session.commit()
    codes = [a.code for a in svc.list_for_company(company.id)]
    assert codes == ["1200", "4000"]


def test_update_renames_account(
    session: Session, company: Company, actor_id: uuid.UUID
) -> None:
    svc = CoaService(session)
    acc = svc.create(actor_id=actor_id, company_id=company.id, code="1200", name="Bank", account_type="asset")
    session.commit()
    updated = svc.update(actor_id=actor_id, company_id=company.id, account_id=acc.id, name="Current Account")
    session.commit()
    assert updated.name == "Current Account"


def test_deactivate_and_filter(
    session: Session, company: Company, actor_id: uuid.UUID
) -> None:
    svc = CoaService(session)
    acc = svc.create(actor_id=actor_id, company_id=company.id, code="1200", name="Bank", account_type="asset")
    session.commit()
    svc.set_active(actor_id=actor_id, company_id=company.id, account_id=acc.id, is_active=False)
    session.commit()

    assert len(svc.list_for_company(company.id, include_inactive=True)) == 1
    assert len(svc.list_for_company(company.id, include_inactive=False)) == 0


def test_update_unknown_account_raises(
    session: Session, company: Company, actor_id: uuid.UUID
) -> None:
    with pytest.raises(AccountNotFoundError):
        CoaService(session).update(
            actor_id=actor_id, company_id=company.id, account_id=uuid.uuid4(), name="X"
        )


def test_account_from_other_company_is_not_found(
    session: Session, company: Company, actor_id: uuid.UUID
) -> None:
    svc = CoaService(session)
    acc = svc.create(actor_id=actor_id, company_id=company.id, code="1200", name="Bank", account_type="asset")
    session.commit()
    # A different company id must not see this account.
    with pytest.raises(AccountNotFoundError):
        svc.update(actor_id=actor_id, company_id=uuid.uuid4(), account_id=acc.id, name="X")


def test_create_is_audited(
    session: Session, company: Company, actor_id: uuid.UUID
) -> None:
    acc = CoaService(session).create(
        actor_id=actor_id, company_id=company.id, code="1200", name="Bank", account_type="asset"
    )
    session.commit()
    audit = session.scalar(
        select(AuditLog).where(
            AuditLog.entity_type == "chart_of_account", AuditLog.entity_id == acc.id
        )
    )
    assert audit is not None
    assert audit.action == "created"


def test_account_persisted_with_correct_columns(
    session: Session, company: Company, actor_id: uuid.UUID
) -> None:
    acc = CoaService(session).create(
        actor_id=actor_id, company_id=company.id, code="5000", name="Costs", account_type="expense"
    )
    session.commit()
    row = session.get(ChartOfAccount, acc.id)
    assert row is not None
    assert row.account_type == "expense"
    assert row.normal_balance == "DR"  # expenses are debit-normal
    assert row.is_active is True
