"""Concurrency test for HLC node-id allocation (PostgreSQL only).

Allocation must be race-safe: many devices registering at once must each receive
a distinct node id. This can only be meaningfully exercised against a database
with real row-level locking, so it runs only when ``LEDGERLINE_TEST_PG_URL`` is
set (CI provides a Postgres service). SQLite serialises writes and cannot
reproduce the race.
"""

from __future__ import annotations

import os
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import create_engine, delete, text
from sqlalchemy.orm import Session

from ledgerline_backend import models  # noqa: F401 — register models
from ledgerline_backend.config import Settings
from ledgerline_backend.models import Device, Organisation, User
from ledgerline_backend.security.device_service import DeviceService

PG_URL = os.environ.get("LEDGERLINE_TEST_PG_URL")

pytestmark = pytest.mark.skipif(
    PG_URL is None,
    reason="LEDGERLINE_TEST_PG_URL not set; concurrency test requires PostgreSQL",
)

_CONCURRENCY = 20


def test_concurrent_registration_allocates_unique_node_ids() -> None:
    assert PG_URL is not None
    engine = create_engine(PG_URL)
    settings = Settings(environment="test", database_url=PG_URL)

    # Clean any prior allocation state and seed a user to register against.
    with Session(engine) as setup:
        setup.execute(delete(Device))
        setup.execute(text("DELETE FROM allocation_counters"))
        org = Organisation(name="Concurrent Org", kind="business")
        setup.add(org)
        setup.flush()
        user = User(
            org_id=org.id, email=f"{uuid.uuid4()}@example.com", display_name="U", status="active"
        )
        setup.add(user)
        setup.commit()
        user_id = user.id

    def register_one(index: int) -> int:
        with Session(engine) as db:
            node_id = DeviceService(db, settings).register(
                user_id=user_id,
                name=f"device-{index}",
                platform="win",
                public_key=bytes([index % 256]),
            ).node_id
            db.commit()
            return node_id

    try:
        with ThreadPoolExecutor(max_workers=_CONCURRENCY) as pool:
            node_ids = list(pool.map(register_one, range(_CONCURRENCY)))
    finally:
        engine.dispose()

    # Every concurrent registration received a distinct node id.
    assert len(node_ids) == _CONCURRENCY
    assert len(set(node_ids)) == _CONCURRENCY
    assert min(node_ids) == 1
    assert max(node_ids) == _CONCURRENCY
