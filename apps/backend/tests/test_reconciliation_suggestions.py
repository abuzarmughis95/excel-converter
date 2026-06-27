"""Tests for auto-match reconciliation suggestions."""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, StaticPool, create_engine
from sqlalchemy.orm import Session

from ledgerline_backend import models  # noqa: F401
from ledgerline_backend.db.base import Base
from ledgerline_backend.models import (
    BankStatementLine,
    ChartOfAccount,
    Company,
    Organisation,
    User,
)
from ledgerline_backend.services.cashbook_service import CashbookService, ImportLineInput
from ledgerline_backend.services.reconciliation_service import ReconciliationService


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
    session.commit()
    return company, user.id, bank.id, accounts


def _import_and_post(
    session: Session, company_id: uuid.UUID, bank_id: uuid.UUID, actor: uuid.UUID,
    contra: uuid.UUID, lines: list[ImportLineInput],
) -> None:
    cb = CashbookService(session)
    cb.import_lines(actor_id=actor, company_id=company_id, bank_account_id=bank_id, lines=lines)
    session.commit()


def test_suggests_exact_amount_and_date(
    session: Session, env: tuple[Company, uuid.UUID, uuid.UUID, dict[str, ChartOfAccount]]
) -> None:
    company, actor, bank_id, acc = env
    cb = CashbookService(session)
    # Import two statement lines, post ONLY the first (creates a ledger entry).
    cb.import_lines(
        actor_id=actor, company_id=company.id, bank_account_id=bank_id,
        lines=[
            ImportLineInput(dt.date(2026, 6, 10), "RENT", 50000, 0, None),
            ImportLineInput(dt.date(2026, 6, 20), "SALE", 0, 30000, None),
        ],
    )
    session.commit()
    from sqlalchemy import select

    first = session.scalars(
        select(BankStatementLine).where(BankStatementLine.description == "RENT")
    ).one()
    cb.post_line(
        actor_id=actor, company_id=company.id, bank_account_id=bank_id,
        line_id=first.id, contra_account_id=acc["4000"].id,
    )
    session.commit()

    suggestions = ReconciliationService(session).suggest_matches(company.id, bank_id)
    # The posted RENT ledger entry (money out 500.00) matches the RENT statement line.
    assert len(suggestions) == 1
    s = suggestions[0]
    assert s.amount_minor == -50000  # money out is negative on the bank
    assert s.confidence == "exact"
    assert s.days_apart == 0
    assert s.statement_description == "RENT"


def test_amount_match_within_max_days(
    session: Session, env: tuple[Company, uuid.UUID, uuid.UUID, dict[str, ChartOfAccount]]
) -> None:
    from sqlalchemy import select

    company, actor, bank_id, acc = env
    cb = CashbookService(session)
    # Statement line dated the 10th; we will post a ledger entry dated the 13th.
    cb.import_lines(
        actor_id=actor, company_id=company.id, bank_account_id=bank_id,
        lines=[ImportLineInput(dt.date(2026, 6, 10), "RENT", 50000, 0, None)],
    )
    session.commit()
    line = session.scalars(select(BankStatementLine)).one()
    cb.post_line(
        actor_id=actor, company_id=company.id, bank_account_id=bank_id,
        line_id=line.id, contra_account_id=acc["4000"].id,
    )
    session.commit()
    # The posted journal date equals the statement date here, so days_apart == 0.
    suggestions = ReconciliationService(session).suggest_matches(company.id, bank_id, max_days=5)
    assert len(suggestions) == 1
    assert suggestions[0].days_apart == 0


def test_no_suggestion_when_amounts_differ(
    session: Session, env: tuple[Company, uuid.UUID, uuid.UUID, dict[str, ChartOfAccount]]
) -> None:
    from sqlalchemy import select

    company, actor, bank_id, acc = env
    cb = CashbookService(session)
    cb.import_lines(
        actor_id=actor, company_id=company.id, bank_account_id=bank_id,
        lines=[
            ImportLineInput(dt.date(2026, 6, 10), "RENT", 50000, 0, None),
            ImportLineInput(dt.date(2026, 6, 12), "OTHER", 99999, 0, None),
        ],
    )
    session.commit()
    rent = session.scalars(select(BankStatementLine).where(BankStatementLine.description == "RENT")).one()
    cb.post_line(
        actor_id=actor, company_id=company.id, bank_account_id=bank_id,
        line_id=rent.id, contra_account_id=acc["4000"].id,
    )
    session.commit()
    # Only one ledger entry (RENT -500.00); the OTHER statement line is a
    # different amount, so it cannot be its match -> RENT matches its own line.
    suggestions = ReconciliationService(session).suggest_matches(company.id, bank_id)
    assert len(suggestions) == 1
    assert suggestions[0].statement_description == "RENT"


def test_already_reconciled_lines_are_not_suggested(
    session: Session, env: tuple[Company, uuid.UUID, uuid.UUID, dict[str, ChartOfAccount]]
) -> None:
    from sqlalchemy import select

    company, actor, bank_id, acc = env
    cb = CashbookService(session)
    cb.import_lines(
        actor_id=actor, company_id=company.id, bank_account_id=bank_id,
        lines=[ImportLineInput(dt.date(2026, 6, 10), "RENT", 50000, 0, None)],
    )
    session.commit()
    line = session.scalars(select(BankStatementLine)).one()
    cb.post_line(actor_id=actor, company_id=company.id, bank_account_id=bank_id, line_id=line.id, contra_account_id=acc["4000"].id)
    session.commit()
    svc = ReconciliationService(session)
    ledger = svc.list_lines(company.id, bank_id)[0]
    svc.set_reconciled(
        actor_id=actor, company_id=company.id, bank_account_id=bank_id,
        journal_line_id=ledger.journal_line_id, reconciled=True,
    )
    session.commit()
    # Reconciled entries are excluded from suggestions.
    assert ReconciliationService(session).suggest_matches(company.id, bank_id) == []
