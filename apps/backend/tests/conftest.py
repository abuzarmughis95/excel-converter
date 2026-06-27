"""Shared pytest fixtures for the backend test suite."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, StaticPool, create_engine, event

from ledgerline_backend import models  # noqa: F401 — register models on metadata
from ledgerline_backend.app import create_app
from ledgerline_backend.config import Settings
from ledgerline_backend.db.base import Base


@pytest.fixture
def settings() -> Settings:
    """Test settings: human-readable logs, test environment."""
    return Settings(environment="test", log_json=False)


@pytest.fixture
def app_engine() -> Iterator[Engine]:
    """A shared in-memory SQLite engine with the schema created.

    StaticPool keeps a single underlying connection so the in-memory database
    persists across sessions opened by request handlers within a test.
    """
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_connection: object, _record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    try:
        yield engine
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture
def client(settings: Settings, app_engine: Engine) -> Iterator[TestClient]:
    """A TestClient bound to a freshly-built app using the in-memory engine."""
    app = create_app(settings, engine=app_engine)
    with TestClient(app) as test_client:
        yield test_client
