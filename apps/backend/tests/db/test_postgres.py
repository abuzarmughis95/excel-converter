"""PostgreSQL-specific migration and type tests.

These run only when ``LEDGERLINE_TEST_PG_URL`` points at a reachable PostgreSQL
instance (set in CI via a service container, or locally against docker-compose).
They are skipped otherwise so the default test run needs no database server.

They assert what SQLite cannot: that the portable GUID maps to a native ``uuid``
column, timestamps are ``timestamptz``, and the migration round-trips on PG.
"""

from __future__ import annotations

import os

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from tests.db.test_migrations import BACKEND_ROOT, REQUIRED_TABLES

PG_URL = os.environ.get("LEDGERLINE_TEST_PG_URL")

pytestmark = pytest.mark.skipif(
    PG_URL is None,
    reason="LEDGERLINE_TEST_PG_URL not set; PostgreSQL integration tests skipped",
)


def _config(url: str) -> Config:
    cfg = Config(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


@pytest.fixture
def clean_pg() -> str:
    """Ensure a clean schema before and after each PG test."""
    assert PG_URL is not None
    cfg = _config(PG_URL)
    command.downgrade(cfg, "base")
    yield PG_URL
    command.downgrade(cfg, "base")


def test_pg_upgrade_creates_all_tables(clean_pg: str) -> None:
    command.upgrade(_config(clean_pg), "head")
    engine = create_engine(clean_pg)
    try:
        tables = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()
    assert REQUIRED_TABLES.issubset(tables)


def test_pg_uses_native_uuid_and_timestamptz(clean_pg: str) -> None:
    command.upgrade(_config(clean_pg), "head")
    engine = create_engine(clean_pg)
    try:
        with engine.connect() as conn:
            id_type = conn.execute(
                text(
                    "SELECT data_type FROM information_schema.columns "
                    "WHERE table_name='organisations' AND column_name='id'"
                )
            ).scalar()
            ts_type = conn.execute(
                text(
                    "SELECT data_type FROM information_schema.columns "
                    "WHERE table_name='organisations' AND column_name='created_at'"
                )
            ).scalar()
    finally:
        engine.dispose()
    assert id_type == "uuid"
    assert ts_type == "timestamp with time zone"


def test_pg_round_trip(clean_pg: str) -> None:
    cfg = _config(clean_pg)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")
    engine = create_engine(clean_pg)
    try:
        tables = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()
    assert REQUIRED_TABLES.isdisjoint(tables)
