"""Fixtures for database-layer tests."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from ledgerline_backend import models  # noqa: F401 — register models on metadata
from ledgerline_backend.db.base import Base
from ledgerline_backend.db.session import create_db_engine, create_session_factory


@pytest.fixture
def engine() -> Iterator[Engine]:
    """An in-memory SQLite engine with the full schema created via metadata."""
    eng = create_db_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(eng)
    try:
        yield eng
    finally:
        Base.metadata.drop_all(eng)
        eng.dispose()


@pytest.fixture
def session_factory(engine: Engine) -> sessionmaker[Session]:
    return create_session_factory(engine)


@pytest.fixture
def session(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    db = session_factory()
    try:
        yield db
    finally:
        db.close()
