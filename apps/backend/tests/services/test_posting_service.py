"""Tests for the PostingService — engine-validated double-entry journals."""

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
    AuditLog,
    ChartOfAccount,
    Company,
    Organisation,
    User,
)
from ledgerline_backend.services.posting_service import (
    AlreadyPostedError,
    InvalidJournalError,
    JournalNotFoundError,
    LineInput,
    NotPostedError,
    PostingService,
    UnbalancedJournalError,
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
def setup(session: Session) -> tuple[Company, uuid.UUID, dict[str, ChartOfAccount]]:
    org = Organisation(name="Org", kind="business")
    session.add(org)
    session.flush()
    user = User(org_id=org.id, email="u@example.com", display_name="U", status="active")
    session.add(user)
    company = Company(org_id=org.id, name="Co", accounts_type="ltd")
    session.add(company)
    session.flush()
    accounts = {}
    for code, name, atype, nb in [
        ("1200", "Bank", "asset", "DR"),
        ("4000", "Sales", "income", "CR"),
        ("2200", "VAT", "liability", "CR"),
        ("5000", "Costs", "expense", "DR"),
    ]:
        a = ChartOfAccount(
            company_id=company.id, code=code, name=name, account_type=atype, normal_balance=nb
        )
        session.add(a)
        accounts[code] = a
    session.commit()
    return company, user.id, accounts


def _line(account: ChartOfAccount, *, dr: int = 0, cr: int = 0) -> LineInput:
    return LineInput(account_id=account.id, debit_minor=dr, credit_minor=cr)


def test_create_balanced_journal(
    session: Session, setup: tuple[Company, uuid.UUID, dict[str, ChartOfAccount]]
) -> None:
    company, actor, acc = setup
    svc = PostingService(session)
    journal = svc.create(
        actor_id=actor,
        company_id=company.id,
        journal_date=DATE,
        lines=[_line(acc["1200"], dr=12000), _line(acc["4000"], cr=12000)],
    )
    session.commit()
    assert journal.is_posted is False
    assert len(journal.lines) == 2
    assert journal.lines[0].debit_minor == 12000


def test_unbalanced_journal_rejected_by_engine(
    session: Session, setup: tuple[Company, uuid.UUID, dict[str, ChartOfAccount]]
) -> None:
    company, actor, acc = setup
    with pytest.raises(UnbalancedJournalError):
        PostingService(session).create(
            actor_id=actor,
            company_id=company.id,
            journal_date=DATE,
            lines=[_line(acc["1200"], dr=12000), _line(acc["4000"], cr=11999)],
        )


def test_multi_line_vat_journal(
    session: Session, setup: tuple[Company, uuid.UUID, dict[str, ChartOfAccount]]
) -> None:
    company, actor, acc = setup
    # Dr Bank 120, Cr Sales 100, Cr VAT 20.
    journal = PostingService(session).create(
        actor_id=actor,
        company_id=company.id,
        journal_date=DATE,
        lines=[
            _line(acc["1200"], dr=12000),
            _line(acc["4000"], cr=10000),
            _line(acc["2200"], cr=2000),
        ],
    )
    session.commit()
    assert len(journal.lines) == 3


def test_journal_needs_two_lines(
    session: Session, setup: tuple[Company, uuid.UUID, dict[str, ChartOfAccount]]
) -> None:
    company, actor, acc = setup
    with pytest.raises(InvalidJournalError):
        PostingService(session).create(
            actor_id=actor, company_id=company.id, journal_date=DATE, lines=[_line(acc["1200"], dr=1)]
        )


def test_line_cannot_be_both_debit_and_credit(
    session: Session, setup: tuple[Company, uuid.UUID, dict[str, ChartOfAccount]]
) -> None:
    company, actor, acc = setup
    with pytest.raises(InvalidJournalError):
        PostingService(session).create(
            actor_id=actor,
            company_id=company.id,
            journal_date=DATE,
            lines=[
                LineInput(account_id=acc["1200"].id, debit_minor=100, credit_minor=100),
                _line(acc["4000"], cr=100),
            ],
        )


def test_unknown_account_rejected(
    session: Session, setup: tuple[Company, uuid.UUID, dict[str, ChartOfAccount]]
) -> None:
    company, actor, acc = setup
    with pytest.raises(InvalidJournalError):
        PostingService(session).create(
            actor_id=actor,
            company_id=company.id,
            journal_date=DATE,
            lines=[
                LineInput(account_id=uuid.uuid4(), debit_minor=100),
                _line(acc["4000"], cr=100),
            ],
        )


def test_inactive_account_rejected(
    session: Session, setup: tuple[Company, uuid.UUID, dict[str, ChartOfAccount]]
) -> None:
    company, actor, acc = setup
    acc["5000"].is_active = False
    session.commit()
    with pytest.raises(InvalidJournalError):
        PostingService(session).create(
            actor_id=actor,
            company_id=company.id,
            journal_date=DATE,
            lines=[_line(acc["5000"], dr=100), _line(acc["4000"], cr=100)],
        )


def test_post_and_unpost(
    session: Session, setup: tuple[Company, uuid.UUID, dict[str, ChartOfAccount]]
) -> None:
    company, actor, acc = setup
    svc = PostingService(session)
    j = svc.create(
        actor_id=actor,
        company_id=company.id,
        journal_date=DATE,
        lines=[_line(acc["1200"], dr=5000), _line(acc["4000"], cr=5000)],
    )
    session.commit()

    posted = svc.post(actor_id=actor, company_id=company.id, journal_id=j.id)
    session.commit()
    assert posted.is_posted is True

    unposted = svc.unpost(
        actor_id=actor, company_id=company.id, journal_id=j.id, reason="correction"
    )
    session.commit()
    assert unposted.is_posted is False


def test_cannot_post_twice(
    session: Session, setup: tuple[Company, uuid.UUID, dict[str, ChartOfAccount]]
) -> None:
    company, actor, acc = setup
    svc = PostingService(session)
    j = svc.create(
        actor_id=actor,
        company_id=company.id,
        journal_date=DATE,
        lines=[_line(acc["1200"], dr=100), _line(acc["4000"], cr=100)],
    )
    session.commit()
    svc.post(actor_id=actor, company_id=company.id, journal_id=j.id)
    session.commit()
    with pytest.raises(AlreadyPostedError):
        svc.post(actor_id=actor, company_id=company.id, journal_id=j.id)


def test_cannot_unpost_a_draft(
    session: Session, setup: tuple[Company, uuid.UUID, dict[str, ChartOfAccount]]
) -> None:
    company, actor, acc = setup
    svc = PostingService(session)
    j = svc.create(
        actor_id=actor,
        company_id=company.id,
        journal_date=DATE,
        lines=[_line(acc["1200"], dr=100), _line(acc["4000"], cr=100)],
    )
    session.commit()
    with pytest.raises(NotPostedError):
        svc.unpost(actor_id=actor, company_id=company.id, journal_id=j.id, reason="x")


def test_unpost_requires_reason(
    session: Session, setup: tuple[Company, uuid.UUID, dict[str, ChartOfAccount]]
) -> None:
    company, actor, acc = setup
    svc = PostingService(session)
    j = svc.create(
        actor_id=actor,
        company_id=company.id,
        journal_date=DATE,
        lines=[_line(acc["1200"], dr=100), _line(acc["4000"], cr=100)],
    )
    session.commit()
    svc.post(actor_id=actor, company_id=company.id, journal_id=j.id)
    session.commit()
    with pytest.raises(InvalidJournalError):
        svc.unpost(actor_id=actor, company_id=company.id, journal_id=j.id, reason="  ")


def test_journal_from_other_company_not_found(
    session: Session, setup: tuple[Company, uuid.UUID, dict[str, ChartOfAccount]]
) -> None:
    company, actor, acc = setup
    svc = PostingService(session)
    j = svc.create(
        actor_id=actor,
        company_id=company.id,
        journal_date=DATE,
        lines=[_line(acc["1200"], dr=100), _line(acc["4000"], cr=100)],
    )
    session.commit()
    with pytest.raises(JournalNotFoundError):
        svc.post(actor_id=actor, company_id=uuid.uuid4(), journal_id=j.id)


def test_create_is_audited(
    session: Session, setup: tuple[Company, uuid.UUID, dict[str, ChartOfAccount]]
) -> None:
    company, actor, acc = setup
    j = PostingService(session).create(
        actor_id=actor,
        company_id=company.id,
        journal_date=DATE,
        lines=[_line(acc["1200"], dr=100), _line(acc["4000"], cr=100)],
    )
    session.commit()
    audit = session.scalar(
        select(AuditLog).where(AuditLog.entity_type == "journal", AuditLog.entity_id == j.id)
    )
    assert audit is not None
    assert audit.action == "created"
