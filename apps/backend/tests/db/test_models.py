"""Tests verifying model creation, defaults, and key constraints.

These exercise the structural foundations only — no posting/transaction logic.
"""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ledgerline_backend.models import (
    AccountingPeriod,
    AuditLog,
    ChartOfAccount,
    Company,
    Organisation,
    SyncEvent,
    User,
)


def _make_org(session: Session) -> Organisation:
    org = Organisation(name="Acme Holdings", kind="business")
    session.add(org)
    session.commit()
    return org


def _make_company(session: Session, org: Organisation) -> Company:
    company = Company(org_id=org.id, name="Acme Ltd", accounts_type="ltd")
    session.add(company)
    session.commit()
    return company


def test_organisation_gets_uuid_pk_and_timestamps(session: Session) -> None:
    org = _make_org(session)
    assert isinstance(org.id, uuid.UUID)
    assert org.id.version == 7
    assert isinstance(org.created_at, dt.datetime)
    assert isinstance(org.updated_at, dt.datetime)
    assert org.version == 1
    assert org.is_deleted is False


def test_user_requires_unique_email(session: Session) -> None:
    org = _make_org(session)
    session.add(User(org_id=org.id, email="a@example.com", display_name="A", status="active"))
    session.commit()
    session.add(User(org_id=org.id, email="a@example.com", display_name="B", status="active"))
    with pytest.raises(IntegrityError):
        session.commit()


def test_company_belongs_to_organisation(session: Session) -> None:
    org = _make_org(session)
    company = _make_company(session, org)
    fetched = session.scalar(select(Company).where(Company.id == company.id))
    assert fetched is not None
    assert fetched.org_id == org.id
    assert fetched.base_currency == "GBP"


def test_accounting_period_unique_per_company_year(session: Session) -> None:
    org = _make_org(session)
    company = _make_company(session, org)
    period = AccountingPeriod(
        company_id=company.id,
        fiscal_year=2026,
        starts_on=dt.date(2026, 4, 6),
        ends_on=dt.date(2027, 4, 5),
        status="open",
    )
    session.add(period)
    session.commit()

    dup = AccountingPeriod(
        company_id=company.id,
        fiscal_year=2026,
        starts_on=dt.date(2026, 4, 6),
        ends_on=dt.date(2027, 4, 5),
        status="open",
    )
    session.add(dup)
    with pytest.raises(IntegrityError):
        session.commit()


def test_chart_of_account_unique_code_per_company(session: Session) -> None:
    org = _make_org(session)
    company = _make_company(session, org)
    session.add(
        ChartOfAccount(
            company_id=company.id,
            code="4000",
            name="Sales",
            account_type="income",
            normal_balance="CR",
        )
    )
    session.commit()
    session.add(
        ChartOfAccount(
            company_id=company.id,
            code="4000",
            name="Other Sales",
            account_type="income",
            normal_balance="CR",
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()


def test_audit_log_persists_with_uuid_pk(session: Session) -> None:
    org = _make_org(session)
    company = _make_company(session, org)
    entry = AuditLog(
        seq=1,
        company_id=company.id,
        entity_type="company",
        entity_id=company.id,
        action="created",
    )
    session.add(entry)
    session.commit()
    assert isinstance(entry.id, uuid.UUID)
    assert isinstance(entry.created_at, dt.datetime)


def test_sync_event_persists_with_payload_and_hlc(session: Session) -> None:
    org = _make_org(session)
    company = _make_company(session, org)
    event = SyncEvent(
        company_id=company.id,
        aggregate_type="company",
        aggregate_id=company.id,
        event_type="CompanyCreated",
        event_version=1,
        payload={"name": "Acme Ltd"},
        hlc_wall=1_700_000_000_000,
        hlc_counter=0,
        node_id=1,
    )
    session.add(event)
    session.commit()
    fetched = session.scalar(select(SyncEvent).where(SyncEvent.id == event.id))
    assert fetched is not None
    assert fetched.payload == {"name": "Acme Ltd"}
    assert fetched.server_seq is None  # not yet assigned by the server


def test_all_required_tables_exist(engine_inspect_tables: list[str]) -> None:
    expected = {
        "organisations",
        "users",
        "companies",
        "accounting_periods",
        "chart_of_accounts",
        "audit_logs",
        "sync_events",
    }
    assert expected.issubset(set(engine_inspect_tables))


@pytest.fixture
def engine_inspect_tables(session: Session) -> list[str]:
    bind = session.get_bind()
    return inspect(bind).get_table_names()
