"""Tests for the bank ReconciliationService."""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, StaticPool, create_engine, select
from sqlalchemy.orm import Session

from ledgerline_backend import models  # noqa: F401
from ledgerline_backend.db.base import Base
from ledgerline_backend.models import (
    BankReconciliationMark,
    ChartOfAccount,
    Company,
    JournalLine,
    Organisation,
    User,
)
from ledgerline_backend.services.cashbook_service import CashbookService, ImportLineInput
from ledgerline_backend.services.reconciliation_service import (
    BankAccountNotFoundError,
    JournalLineNotFoundError,
    ReconciliationService,
)

DATE = dt.date(2026, 6, 27)


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
def env(session: Session) -> tuple[Company, uuid.UUID, uuid.UUID, dict[str, ChartOfAccount]]:
    org = Organisation(name="Org", kind="business")
    session.add(org)
    session.flush()
    user = User(org_id=org.id, email="u@example.com", display_name="U", status="active")
    company = Company(org_id=org.id, name="Co", accounts_type="ltd")
    session.add_all([user, company])
    session.flush()
    accounts = {}
    for code, name, atype, nb in [
        ("1200", "Bank", "asset", "DR"),
        ("4000", "Sales", "income", "CR"),
    ]:
        a = ChartOfAccount(company_id=company.id, code=code, name=name, account_type=atype, normal_balance=nb)
        session.add(a)
        accounts[code] = a
    session.flush()
    cb = CashbookService(session)
    bank = cb.create_bank_account(actor_id=user.id, company_id=company.id, name="Current", gl_account_id=accounts["1200"].id)
    # Import + post two received lines (money in -> Dr bank).
    cb.import_lines(
        actor_id=user.id, company_id=company.id, bank_account_id=bank.id,
        lines=[
            ImportLineInput(DATE, "SALE A", 0, 10000, None),
            ImportLineInput(DATE, "SALE B", 0, 25000, None),
        ],
    )
    session.commit()
    from ledgerline_backend.models import BankStatementLine

    for line in session.scalars(select(BankStatementLine)).all():
        cb.post_line(actor_id=user.id, company_id=company.id, bank_account_id=bank.id, line_id=line.id, contra_account_id=accounts["4000"].id)
    session.commit()
    return company, user.id, bank.id, accounts


def test_list_lines_shows_bank_entries_unreconciled(
    session: Session, env: tuple[Company, uuid.UUID, uuid.UUID, dict[str, ChartOfAccount]]
) -> None:
    company, _, bank_id, _ = env
    lines = ReconciliationService(session).list_lines(company.id, bank_id)
    # Two journals posted, each with a Dr-bank line.
    assert len(lines) == 2
    assert all(not line.reconciled for line in lines)
    assert {line.amount_minor for line in lines} == {10000, 25000}


def test_set_reconciled_and_summary(
    session: Session, env: tuple[Company, uuid.UUID, uuid.UUID, dict[str, ChartOfAccount]]
) -> None:
    company, actor, bank_id, _ = env
    svc = ReconciliationService(session)
    lines = svc.list_lines(company.id, bank_id)
    first = lines[0]

    svc.set_reconciled(
        actor_id=actor, company_id=company.id, bank_account_id=bank_id,
        journal_line_id=first.journal_line_id, reconciled=True,
    )
    session.commit()

    summary = svc.summary(company.id, bank_id, statement_balance_minor=first.amount_minor)
    # Ledger holds both lines; reconciled holds only the ticked one.
    assert summary.ledger_balance_minor == 35000
    assert summary.reconciled_balance_minor == first.amount_minor
    assert summary.unreconciled_count == 1
    # Statement balance == reconciled -> difference zero.
    assert summary.difference_minor == 0


def test_untick_removes_mark(
    session: Session, env: tuple[Company, uuid.UUID, uuid.UUID, dict[str, ChartOfAccount]]
) -> None:
    company, actor, bank_id, _ = env
    svc = ReconciliationService(session)
    line = svc.list_lines(company.id, bank_id)[0]
    svc.set_reconciled(actor_id=actor, company_id=company.id, bank_account_id=bank_id, journal_line_id=line.journal_line_id, reconciled=True)
    session.commit()
    assert len(list(session.scalars(select(BankReconciliationMark)).all())) == 1
    svc.set_reconciled(actor_id=actor, company_id=company.id, bank_account_id=bank_id, journal_line_id=line.journal_line_id, reconciled=False)
    session.commit()
    assert len(list(session.scalars(select(BankReconciliationMark)).all())) == 0


def test_reconcile_unknown_line_raises(
    session: Session, env: tuple[Company, uuid.UUID, uuid.UUID, dict[str, ChartOfAccount]]
) -> None:
    company, actor, bank_id, _ = env
    with pytest.raises(JournalLineNotFoundError):
        ReconciliationService(session).set_reconciled(
            actor_id=actor, company_id=company.id, bank_account_id=bank_id,
            journal_line_id=uuid.uuid4(), reconciled=True,
        )


def test_unknown_bank_account_raises(session: Session) -> None:
    with pytest.raises(BankAccountNotFoundError):
        ReconciliationService(session).list_lines(uuid.uuid4(), uuid.uuid4())


def test_summary_difference_none_without_statement_balance(
    session: Session, env: tuple[Company, uuid.UUID, uuid.UUID, dict[str, ChartOfAccount]]
) -> None:
    company, _, bank_id, _ = env
    summary = ReconciliationService(session).summary(company.id, bank_id)
    assert summary.difference_minor is None
    assert summary.statement_balance_minor is None


def test_non_bank_line_not_reconcilable(
    session: Session, env: tuple[Company, uuid.UUID, uuid.UUID, dict[str, ChartOfAccount]]
) -> None:
    # A Sales (4000) line must not appear in the bank reconciliation list.
    company, _, bank_id, acc = env
    sales_line = session.scalar(
        select(JournalLine).where(JournalLine.account_id == acc["4000"].id)
    )
    assert sales_line is not None
    lines = ReconciliationService(session).list_lines(company.id, bank_id)
    assert sales_line.id not in {line.journal_line_id for line in lines}
