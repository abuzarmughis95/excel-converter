"""Tests for the session factory and transactional scope helper."""

from __future__ import annotations

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, sessionmaker

from ledgerline_backend.db.session import session_scope
from ledgerline_backend.models import Organisation


def test_session_scope_commits_on_success(
    session_factory: sessionmaker[Session], engine: Engine
) -> None:
    with session_scope(session_factory) as db:
        db.add(Organisation(name="Committed", kind="business"))

    with Session(engine) as verify:
        names = verify.scalars(select(Organisation.name)).all()
    assert "Committed" in names


def test_session_scope_rolls_back_on_error(
    session_factory: sessionmaker[Session], engine: Engine
) -> None:
    class BoomError(Exception):
        pass

    with pytest.raises(BoomError):
        with session_scope(session_factory) as db:
            db.add(Organisation(name="RolledBack", kind="business"))
            db.flush()
            raise BoomError

    with Session(engine) as verify:
        names = verify.scalars(select(Organisation.name)).all()
    assert "RolledBack" not in names
