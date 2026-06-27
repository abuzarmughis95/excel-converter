"""Tests for the tamper-evident audit writer."""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, StaticPool, create_engine, desc, select
from sqlalchemy.orm import Session

from ledgerline_backend import models  # noqa: F401 — register models
from ledgerline_backend.db.base import Base
from ledgerline_backend.models import AuditLog
from ledgerline_backend.services.audit import record_audit


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


def test_first_entry_has_no_prev_hash(session: Session) -> None:
    entry = record_audit(
        session, entity_type="company", entity_id=uuid.uuid4(), action="created"
    )
    session.commit()
    assert entry.prev_hash is None
    assert entry.this_hash is not None


def test_chain_links_entries_for_same_aggregate(session: Session) -> None:
    entity = uuid.uuid4()
    first = record_audit(session, entity_type="company", entity_id=entity, action="created")
    session.commit()
    second = record_audit(session, entity_type="company", entity_id=entity, action="updated")
    session.commit()

    # The second entry for the SAME aggregate chains to the first.
    assert second.prev_hash == first.this_hash
    assert second.this_hash != first.this_hash


def test_chains_are_independent_per_aggregate(session: Session) -> None:
    a = record_audit(session, entity_type="company", entity_id=uuid.uuid4(), action="created")
    session.commit()
    b = record_audit(session, entity_type="company", entity_id=uuid.uuid4(), action="created")
    session.commit()

    # Different aggregates each start their own chain.
    assert a.prev_hash is None
    assert b.prev_hash is None


def test_chain_is_verifiable(session: Session) -> None:
    import hashlib

    entity = uuid.uuid4()
    for i in range(5):
        record_audit(session, entity_type="company", entity_id=entity, action=f"a{i}")
    session.commit()

    entries = list(
        session.scalars(
            select(AuditLog).where(AuditLog.entity_id == entity).order_by(AuditLog.seq)
        ).all()
    )
    prev = None
    for e in entries:
        assert e.prev_hash == prev
        assert e.this_hash is not None
        assert isinstance(e.this_hash, bytes)
        assert len(e.this_hash) == hashlib.sha256().digest_size
        prev = e.this_hash


def test_seq_is_monotonic_for_rapid_same_entity_writes(session: Session) -> None:
    """Rapid writes (same created_at) must still chain correctly via seq."""
    entity = uuid.uuid4()
    entries = [
        record_audit(session, entity_type="company", entity_id=entity, action=f"a{i}")
        for i in range(10)
    ]
    session.commit()

    # seq strictly increases in creation order, regardless of created_at ties.
    seqs = [e.seq for e in entries]
    assert seqs == sorted(seqs)
    assert len(set(seqs)) == 10

    # And the chain holds when ordered by seq.
    ordered = list(
        session.scalars(
            select(AuditLog).where(AuditLog.entity_id == entity).order_by(AuditLog.seq)
        ).all()
    )
    prev = None
    for e in ordered:
        assert e.prev_hash == prev
        prev = e.this_hash


def test_head_is_most_recent(session: Session) -> None:
    record_audit(session, entity_type="x", entity_id=uuid.uuid4(), action="first")
    session.commit()
    last = record_audit(session, entity_type="x", entity_id=uuid.uuid4(), action="last")
    session.commit()
    head = session.scalar(select(AuditLog).order_by(desc(AuditLog.seq)).limit(1))
    assert head is not None
    assert head.this_hash == last.this_hash
