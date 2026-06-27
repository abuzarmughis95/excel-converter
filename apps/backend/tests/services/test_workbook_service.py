"""Tests for the WorkbookService (multi-sheet spreadsheet load/save)."""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, StaticPool, create_engine, select
from sqlalchemy.orm import Session

from ledgerline_backend import models  # noqa: F401 — register models
from ledgerline_backend.db.base import Base
from ledgerline_backend.models import AuditLog, Company, Organisation, Sheet, User
from ledgerline_backend.services.workbook_service import (
    MAX_SHEETS,
    SheetInput,
    WorkbookError,
    WorkbookService,
    WorkbookTooLargeError,
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
def setup(session: Session) -> tuple[uuid.UUID, uuid.UUID]:
    org = Organisation(name="Org", kind="business")
    session.add(org)
    session.flush()
    user = User(org_id=org.id, email="u@example.com", display_name="U", status="active")
    company = Company(org_id=org.id, name="Co", accounts_type="ltd")
    session.add_all([user, company])
    session.commit()
    return company.id, user.id


def test_load_creates_default_workbook_with_one_sheet(
    session: Session, setup: tuple[uuid.UUID, uuid.UUID]
) -> None:
    company_id, _ = setup
    wb = WorkbookService(session).load(company_id)
    session.commit()
    assert wb.name == "Workbook"
    assert len(wb.sheets) == 1
    assert wb.sheets[0].name == "Sheet1"


def test_save_replaces_sheets(
    session: Session, setup: tuple[uuid.UUID, uuid.UUID]
) -> None:
    company_id, actor = setup
    svc = WorkbookService(session)
    saved = svc.save(
        actor_id=actor,
        company_id=company_id,
        sheets=[
            SheetInput(name="Receipts", cells=[["Date", "Amount"], ["2026-06-27", "100.00"]]),
            SheetInput(name="Payments", cells=[["Date", "Amount"]]),
        ],
    )
    session.commit()
    assert [s.name for s in saved.sheets] == ["Receipts", "Payments"]
    assert saved.sheets[0].cells[1] == ["2026-06-27", "100.00"]


def test_save_then_load_roundtrip(
    session: Session, setup: tuple[uuid.UUID, uuid.UUID]
) -> None:
    company_id, actor = setup
    svc = WorkbookService(session)
    svc.save(
        actor_id=actor,
        company_id=company_id,
        sheets=[SheetInput(name="VAT", cells=[["Box1", "1000.00"]])],
    )
    session.commit()
    loaded = svc.load(company_id)
    assert len(loaded.sheets) == 1
    assert loaded.sheets[0].name == "VAT"
    assert loaded.sheets[0].cells == [["Box1", "1000.00"]]


def test_save_rejects_duplicate_sheet_names(
    session: Session, setup: tuple[uuid.UUID, uuid.UUID]
) -> None:
    company_id, actor = setup
    with pytest.raises(WorkbookError):
        WorkbookService(session).save(
            actor_id=actor,
            company_id=company_id,
            sheets=[SheetInput(name="A"), SheetInput(name="A")],
        )


def test_save_rejects_blank_sheet_name(
    session: Session, setup: tuple[uuid.UUID, uuid.UUID]
) -> None:
    company_id, actor = setup
    with pytest.raises(WorkbookError):
        WorkbookService(session).save(
            actor_id=actor, company_id=company_id, sheets=[SheetInput(name="  ")]
        )


def test_save_rejects_too_many_sheets(
    session: Session, setup: tuple[uuid.UUID, uuid.UUID]
) -> None:
    company_id, actor = setup
    sheets = [SheetInput(name=f"S{i}") for i in range(MAX_SHEETS + 1)]
    with pytest.raises(WorkbookTooLargeError):
        WorkbookService(session).save(actor_id=actor, company_id=company_id, sheets=sheets)


def test_save_is_audited(
    session: Session, setup: tuple[uuid.UUID, uuid.UUID]
) -> None:
    company_id, actor = setup
    WorkbookService(session).save(
        actor_id=actor, company_id=company_id, sheets=[SheetInput(name="A")]
    )
    session.commit()
    audit = session.scalar(select(AuditLog).where(AuditLog.entity_type == "workbook"))
    assert audit is not None
    assert audit.action == "saved"


def test_save_does_not_leak_sheets_across_companies(
    session: Session, setup: tuple[uuid.UUID, uuid.UUID]
) -> None:
    company_id, actor = setup
    WorkbookService(session).save(
        actor_id=actor, company_id=company_id, sheets=[SheetInput(name="Mine")]
    )
    session.commit()
    # Every sheet belongs to this company's workbook only.
    total_sheets = len(list(session.scalars(select(Sheet)).all()))
    assert total_sheets == 1
