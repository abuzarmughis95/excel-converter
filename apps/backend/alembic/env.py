"""Alembic migration environment.

The database URL is taken from application Settings (env-driven) rather than
alembic.ini, and ``target_metadata`` is the shared declarative Base so
autogenerate sees every model. Importing ``ledgerline_backend.models`` registers
all tables on the metadata.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy.engine import Connection

from ledgerline_backend import models  # noqa: F401 — registers models on metadata
from ledgerline_backend.config import get_settings
from ledgerline_backend.db.base import Base
from ledgerline_backend.db.session import create_db_engine

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _database_url() -> str:
    # Allow an explicit override (e.g. tests) via the standard Alembic option,
    # otherwise fall back to application settings.
    override = config.get_main_option("sqlalchemy.url")
    if override:
        return override
    return get_settings().database_url


def run_migrations_offline() -> None:
    """Run migrations without a live DB connection (emits SQL)."""
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        # batch mode is required for SQLite ALTER support and is harmless on PG.
        render_as_batch=True,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live connection."""
    engine = create_db_engine(_database_url())
    try:
        with engine.connect() as connection:
            _do_run_migrations(connection)
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
