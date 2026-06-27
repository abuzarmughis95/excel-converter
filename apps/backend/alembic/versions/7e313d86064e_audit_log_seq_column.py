"""audit log seq column

Adds a strictly-monotonic ``seq`` to audit_logs (the authoritative chain order)
and seeds the application-side allocation counter so new entries continue from
the current maximum. Existing rows are backfilled deterministically by
``created_at`` then ``id`` so the migration is safe on a populated table.

Revision ID: 7e313d86064e
Revises: f1227cec12db
Create Date: 2026-06-18
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import ledgerline_backend.db.base  # noqa: F401

revision: str = "7e313d86064e"
down_revision: str | None = "f1227cec12db"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()

    # 1. Add the column as nullable so existing rows are allowed.
    with op.batch_alter_table("audit_logs", schema=None) as batch_op:
        batch_op.add_column(sa.Column("seq", sa.BigInteger(), nullable=True))

    # 2. Backfill existing rows deterministically (created_at, then id).
    rows = bind.execute(
        sa.text("SELECT id FROM audit_logs ORDER BY created_at, id")
    ).fetchall()
    for index, row in enumerate(rows, start=1):
        bind.execute(
            sa.text("UPDATE audit_logs SET seq = :seq WHERE id = :id"),
            {"seq": index, "id": row[0]},
        )

    # 3. Enforce NOT NULL + uniqueness now that every row has a value.
    with op.batch_alter_table("audit_logs", schema=None) as batch_op:
        batch_op.alter_column("seq", existing_type=sa.BigInteger(), nullable=False)
        batch_op.create_unique_constraint("uq_audit_log_seq", ["seq"])

    # 4. Seed the allocation counter so new entries continue from max(seq).
    max_seq = len(rows)
    existing = bind.execute(
        sa.text("SELECT value FROM allocation_counters WHERE name = 'audit_seq'")
    ).fetchone()
    if existing is None:
        bind.execute(
            sa.text(
                "INSERT INTO allocation_counters (name, value) VALUES ('audit_seq', :v)"
            ),
            {"v": max_seq},
        )
    else:
        bind.execute(
            sa.text("UPDATE allocation_counters SET value = :v WHERE name = 'audit_seq'"),
            {"v": max_seq},
        )


def downgrade() -> None:
    bind = op.get_bind()
    with op.batch_alter_table("audit_logs", schema=None) as batch_op:
        batch_op.drop_constraint("uq_audit_log_seq", type_="unique")
        batch_op.drop_column("seq")
    bind.execute(sa.text("DELETE FROM allocation_counters WHERE name = 'audit_seq'"))
