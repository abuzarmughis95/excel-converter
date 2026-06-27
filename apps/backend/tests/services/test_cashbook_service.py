"""Tests for the CashbookService — bank accounts, import, and posting."""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, StaticPool, create_engine, select
from sqlalchemy.orm import Session

from ledgerline_backend import models  # noqa: F401 — register models
from ledgerline_backend.db.base import Base
from ledgerline_backend.models import (
    BankStatementLine,
    ChartOfAccount,
    Company,
    Journal,
    Organisation,
    User,
)
from ledgerline_backend.services.cashbook_service import (
    BankAccountNotFoundError,
    CashbookService,
    GLAccountInvalidError,
    ImportLineInput,
    LineAlreadyPostedError,
)
from ledgerline_backend.services.posting_service import InvalidJournalError
from ledgerline_backend.services.reports_service import ReportsService

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
def env(session: Session) -> tuple[Company, uuid.UUID, dict[str, ChartOfAccount]]:
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
        ("5000", "Costs", "expense", "DR"),
    ]:
        a = ChartOfAccount(
            company_id=company.id, code=code, name=name, account_type=atype, normal_balance=nb
        )
        session.add(a)
        accounts[code] = a
    session.commit()
    return company, user.id, accounts


def _bank(svc: CashbookService, company: Company, actor: uuid.UUID, gl: ChartOfAccount) -> uuid.UUID:
    return svc.create_bank_account(
        actor_id=actor, company_id=company.id, name="Current", gl_account_id=gl.id
    ).id


def test_create_bank_account(
    session: Session, env: tuple[Company, uuid.UUID, dict[str, ChartOfAccount]]
) -> None:
    company, actor, acc = env
    svc = CashbookService(session)
    ba = svc.create_bank_account(
        actor_id=actor, company_id=company.id, name="Current", gl_account_id=acc["1200"].id
    )
    session.commit()
    assert ba.name == "Current"
    assert ba.gl_account_id == acc["1200"].id


def test_create_bank_account_rejects_foreign_gl(
    session: Session, env: tuple[Company, uuid.UUID, dict[str, ChartOfAccount]]
) -> None:
    company, actor, _ = env
    with pytest.raises(GLAccountInvalidError):
        CashbookService(session).create_bank_account(
            actor_id=actor, company_id=company.id, name="X", gl_account_id=uuid.uuid4()
        )


def test_import_lines_and_dedupe(
    session: Session, env: tuple[Company, uuid.UUID, dict[str, ChartOfAccount]]
) -> None:
    company, actor, acc = env
    svc = CashbookService(session)
    bank_id = _bank(svc, company, actor, acc["1200"])
    lines = [
        ImportLineInput(line_date=DATE, description="SALES", money_out_minor=0, money_in_minor=20000, balance_minor=None),
        ImportLineInput(line_date=DATE, description="RENT", money_out_minor=50000, money_in_minor=0, balance_minor=None),
    ]
    first = svc.import_lines(actor_id=actor, company_id=company.id, bank_account_id=bank_id, lines=lines)
    session.commit()
    assert first.imported == 2
    assert first.duplicates == 0

    # Re-import the same lines -> all duplicates.
    second = svc.import_lines(actor_id=actor, company_id=company.id, bank_account_id=bank_id, lines=lines)
    session.commit()
    assert second.imported == 0
    assert second.duplicates == 2


def test_import_to_unknown_account_raises(
    session: Session, env: tuple[Company, uuid.UUID, dict[str, ChartOfAccount]]
) -> None:
    company, actor, _ = env
    with pytest.raises(BankAccountNotFoundError):
        CashbookService(session).import_lines(
            actor_id=actor,
            company_id=company.id,
            bank_account_id=uuid.uuid4(),
            lines=[ImportLineInput(DATE, "x", 0, 100, None)],
        )


def test_post_money_in_creates_balanced_journal(
    session: Session, env: tuple[Company, uuid.UUID, dict[str, ChartOfAccount]]
) -> None:
    company, actor, acc = env
    svc = CashbookService(session)
    bank_id = _bank(svc, company, actor, acc["1200"])
    svc.import_lines(
        actor_id=actor,
        company_id=company.id,
        bank_account_id=bank_id,
        lines=[ImportLineInput(DATE, "SALES", 0, 20000, None)],
    )
    session.commit()
    line = session.scalar(select(BankStatementLine))
    assert line is not None

    journal_id = svc.post_line(
        actor_id=actor,
        company_id=company.id,
        bank_account_id=bank_id,
        line_id=line.id,
        contra_account_id=acc["4000"].id,
    )
    session.commit()

    # The journal exists and is posted.
    journal = session.get(Journal, journal_id)
    assert journal is not None
    assert journal.is_posted is True

    # Money in -> Dr Bank, Cr Sales: appears in the trial balance.
    tb = {r.account_code: (r.debit_minor, r.credit_minor) for r in ReportsService(session).trial_balance(company.id)}
    assert tb["1200"] == (20000, 0)
    assert tb["4000"] == (0, 20000)

    # The line is marked posted.
    session.refresh(line)
    assert line.is_posted is True
    assert line.posted_journal_id == journal_id


def test_post_money_out_direction(
    session: Session, env: tuple[Company, uuid.UUID, dict[str, ChartOfAccount]]
) -> None:
    company, actor, acc = env
    svc = CashbookService(session)
    bank_id = _bank(svc, company, actor, acc["1200"])
    svc.import_lines(
        actor_id=actor,
        company_id=company.id,
        bank_account_id=bank_id,
        lines=[ImportLineInput(DATE, "RENT", 50000, 0, None)],
    )
    session.commit()
    line = session.scalar(select(BankStatementLine))
    assert line is not None
    svc.post_line(
        actor_id=actor,
        company_id=company.id,
        bank_account_id=bank_id,
        line_id=line.id,
        contra_account_id=acc["5000"].id,
    )
    session.commit()
    # Money out -> Dr Costs, Cr Bank.
    tb = {r.account_code: (r.debit_minor, r.credit_minor) for r in ReportsService(session).trial_balance(company.id)}
    assert tb["5000"] == (50000, 0)
    assert tb["1200"] == (0, 50000)


def test_cannot_post_a_line_twice(
    session: Session, env: tuple[Company, uuid.UUID, dict[str, ChartOfAccount]]
) -> None:
    company, actor, acc = env
    svc = CashbookService(session)
    bank_id = _bank(svc, company, actor, acc["1200"])
    svc.import_lines(
        actor_id=actor,
        company_id=company.id,
        bank_account_id=bank_id,
        lines=[ImportLineInput(DATE, "SALES", 0, 100, None)],
    )
    session.commit()
    line = session.scalar(select(BankStatementLine))
    assert line is not None
    svc.post_line(
        actor_id=actor, company_id=company.id, bank_account_id=bank_id, line_id=line.id,
        contra_account_id=acc["4000"].id,
    )
    session.commit()
    with pytest.raises(LineAlreadyPostedError):
        svc.post_line(
            actor_id=actor, company_id=company.id, bank_account_id=bank_id, line_id=line.id,
            contra_account_id=acc["4000"].id,
        )


def test_post_zero_amount_line_rejected(
    session: Session, env: tuple[Company, uuid.UUID, dict[str, ChartOfAccount]]
) -> None:
    company, actor, acc = env
    svc = CashbookService(session)
    bank_id = _bank(svc, company, actor, acc["1200"])
    svc.import_lines(
        actor_id=actor,
        company_id=company.id,
        bank_account_id=bank_id,
        lines=[ImportLineInput(DATE, "ZERO", 0, 0, None)],
    )
    session.commit()
    line = session.scalar(select(BankStatementLine))
    assert line is not None
    with pytest.raises(InvalidJournalError):
        svc.post_line(
            actor_id=actor, company_id=company.id, bank_account_id=bank_id, line_id=line.id,
            contra_account_id=acc["4000"].id,
        )
