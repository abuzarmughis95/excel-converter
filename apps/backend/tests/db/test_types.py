"""Tests for the portable GUID type and SQLite session configuration."""

from __future__ import annotations

import uuid

from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from ledgerline_backend.db.ids import uuid7
from ledgerline_backend.models import Organisation


def test_guid_round_trips_as_uuid(session: Session) -> None:
    org = Organisation(name="RoundTrip", kind="business")
    session.add(org)
    session.commit()
    original_id = org.id

    session.expunge_all()
    fetched = session.get(Organisation, original_id)
    assert fetched is not None
    assert isinstance(fetched.id, uuid.UUID)
    assert fetched.id == original_id


def test_guid_accepts_string_form(session: Session) -> None:
    explicit = uuid7()
    org = Organisation(id=explicit, name="Explicit", kind="business")
    session.add(org)
    session.commit()
    fetched = session.get(Organisation, str(explicit))
    assert fetched is not None
    assert fetched.id == explicit


def test_sqlite_foreign_keys_enabled(engine: Engine) -> None:
    with engine.connect() as conn:
        result = conn.execute(text("PRAGMA foreign_keys")).scalar()
    assert result == 1
