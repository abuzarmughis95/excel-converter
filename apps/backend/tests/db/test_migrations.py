"""Tests that Alembic migrations run cleanly and produce the expected schema.

The migration is exercised end-to-end against a temporary SQLite database:
upgrade to head, assert the schema, downgrade to base, and upgrade again to prove
the round-trip is clean (acceptance criterion: migrations run cleanly).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

BACKEND_ROOT = Path(__file__).resolve().parents[2]

REQUIRED_TABLES = {
    "organisations",
    "users",
    "companies",
    "accounting_periods",
    "chart_of_accounts",
    "audit_logs",
    "sync_events",
}


def _alembic_config(db_url: str) -> Config:
    cfg = Config(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", db_url)
    return cfg


@pytest.fixture
def db_url(tmp_path: Path) -> str:
    return f"sqlite:///{tmp_path / 'migtest.sqlite'}"


def test_upgrade_creates_all_tables(db_url: str) -> None:
    command.upgrade(_alembic_config(db_url), "head")
    engine = create_engine(db_url)
    try:
        tables = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()
    assert REQUIRED_TABLES.issubset(tables)


def test_audit_seq_migration_backfills_existing_rows(db_url: str) -> None:
    """The seq migration must backfill rows that predate the column."""
    cfg = _alembic_config(db_url)
    # Migrate to the revision just before the seq column was added.
    command.upgrade(cfg, "f1227cec12db")

    engine = create_engine(db_url)
    try:
        with engine.begin() as conn:
            for i in range(3):
                conn.execute(
                    text(
                        "INSERT INTO audit_logs (id, entity_type, entity_id, action, created_at) "
                        "VALUES (:id, 'company', :eid, 'created', :ts)"
                    ),
                    {
                        "id": f"00000000-0000-7000-8000-00000000000{i}",
                        "eid": f"00000000-0000-7000-8000-0000000000a{i}",
                        "ts": f"2026-06-18T10:00:0{i}",
                    },
                )

        # Now apply the seq migration.
        command.upgrade(cfg, "7e313d86064e")

        with engine.connect() as conn:
            null_seqs = conn.execute(
                text("SELECT count(*) FROM audit_logs WHERE seq IS NULL")
            ).scalar()
            distinct = conn.execute(text("SELECT count(DISTINCT seq) FROM audit_logs")).scalar()
            counter = conn.execute(
                text("SELECT value FROM allocation_counters WHERE name = 'audit_seq'")
            ).scalar()
    finally:
        engine.dispose()

    assert null_seqs == 0
    assert distinct == 3  # each row got a unique seq
    assert counter == 3  # counter seeded to max so new entries continue from 4


def test_downgrade_then_upgrade_round_trip(db_url: str) -> None:
    cfg = _alembic_config(db_url)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")

    engine = create_engine(db_url)
    try:
        tables_after_down = set(inspect(engine).get_table_names())
        assert REQUIRED_TABLES.isdisjoint(tables_after_down)
    finally:
        engine.dispose()

    command.upgrade(cfg, "head")
    engine = create_engine(db_url)
    try:
        tables_after_up = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()
    assert REQUIRED_TABLES.issubset(tables_after_up)


def test_check_constraint_rejects_invalid_account_type(db_url: str) -> None:
    command.upgrade(_alembic_config(db_url), "head")
    engine = create_engine(db_url)
    # SQLite enforces CHECK constraints but not FKs unless enabled; CHECK is what
    # we assert here. An invalid account_type must be rejected.
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO organisations (id, name, kind, version, is_deleted) "
                 "VALUES ('11111111-1111-7111-8111-111111111111', 'O', 'business', 1, 0)")
        )
        conn.execute(
            text(
                "INSERT INTO companies (id, org_id, name, base_currency, accounts_type, version, is_deleted) "
                "VALUES ('22222222-2222-7222-8222-222222222222', "
                "'11111111-1111-7111-8111-111111111111', 'C', 'GBP', 'ltd', 1, 0)"
            )
        )
    with pytest.raises(Exception):  # noqa: B017 — DBAPI raises a dialect-specific IntegrityError
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO chart_of_accounts "
                    "(id, company_id, code, name, account_type, normal_balance, is_control, is_active, version, is_deleted) "
                    "VALUES ('33333333-3333-7333-8333-333333333333', "
                    "'22222222-2222-7222-8222-222222222222', '4000', 'Sales', 'INVALID', 'CR', 0, 1, 1, 0)"
                )
            )
    engine.dispose()
