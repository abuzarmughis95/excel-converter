"""HTTP-level tests for accounting periods + the posting lock."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from ledgerline_backend.models import Organisation


@pytest.fixture
def org_id(app_engine: Engine) -> uuid.UUID:
    with Session(app_engine) as db:
        org = Organisation(name="Org", kind="business")
        db.add(org)
        db.commit()
        return org.id


def _register(client: TestClient, org_id: uuid.UUID, email: str) -> None:
    client.post(
        "/v1/auth/register",
        json={"org_id": str(org_id), "email": email, "display_name": "U", "password": "password123"},
    )


def _auth(client: TestClient, email: str) -> dict[str, str]:
    login = client.post("/v1/auth/login", json={"email": email, "password": "password123"}).json()
    return {"Authorization": f"Bearer {login['access_token']}"}


def _setup(client: TestClient, org_id: uuid.UUID) -> tuple[dict[str, str], str, dict[str, str]]:
    _register(client, org_id, "owner@example.com")
    owner = _auth(client, "owner@example.com")
    cid = client.post("/v1/companies", json={"name": "Co"}, headers=owner).json()["id"]
    acc = {}
    for code, name, atype in [("1200", "Bank", "asset"), ("4000", "Sales", "income")]:
        acc[code] = client.post(
            f"/v1/companies/{cid}/accounts",
            json={"code": code, "name": name, "account_type": atype},
            headers=owner,
        ).json()["id"]
    return owner, cid, acc


def _draft(client: TestClient, cid: str, owner: dict[str, str], acc: dict[str, str], date: str) -> str:
    return client.post(
        f"/v1/companies/{cid}/journals",
        json={"journal_date": date, "lines": [
            {"account_id": acc["1200"], "debit_minor": 10000},
            {"account_id": acc["4000"], "credit_minor": 10000},
        ]},
        headers=owner,
    ).json()["id"]


def test_create_list_and_transition_period(client: TestClient, org_id: uuid.UUID) -> None:
    owner, cid, _ = _setup(client, org_id)
    created = client.post(
        f"/v1/companies/{cid}/periods",
        json={"fiscal_year": 2026, "starts_on": "2026-01-01", "ends_on": "2026-12-31"},
        headers=owner,
    )
    assert created.status_code == 201
    pid = created.json()["id"]
    assert created.json()["status"] == "open"

    listed = client.get(f"/v1/companies/{cid}/periods", headers=owner)
    assert listed.status_code == 200
    assert len(listed.json()) == 1

    # open -> soft_closed -> locked.
    sc = client.post(f"/v1/companies/{cid}/periods/{pid}/status", json={"status": "soft_closed"}, headers=owner)
    assert sc.json()["status"] == "soft_closed"
    lk = client.post(f"/v1/companies/{cid}/periods/{pid}/status", json={"status": "locked"}, headers=owner)
    assert lk.json()["status"] == "locked"


def test_locked_period_is_terminal(client: TestClient, org_id: uuid.UUID) -> None:
    owner, cid, _ = _setup(client, org_id)
    pid = client.post(
        f"/v1/companies/{cid}/periods",
        json={"fiscal_year": 2026, "starts_on": "2026-01-01", "ends_on": "2026-12-31"},
        headers=owner,
    ).json()["id"]
    client.post(f"/v1/companies/{cid}/periods/{pid}/status", json={"status": "locked"}, headers=owner)
    # locked -> open is illegal.
    bad = client.post(f"/v1/companies/{cid}/periods/{pid}/status", json={"status": "open"}, headers=owner)
    assert bad.status_code == 422


def test_overlapping_period_rejected(client: TestClient, org_id: uuid.UUID) -> None:
    owner, cid, _ = _setup(client, org_id)
    client.post(
        f"/v1/companies/{cid}/periods",
        json={"fiscal_year": 2026, "starts_on": "2026-01-01", "ends_on": "2026-12-31"},
        headers=owner,
    )
    overlap = client.post(
        f"/v1/companies/{cid}/periods",
        json={"fiscal_year": 2027, "starts_on": "2026-06-01", "ends_on": "2027-05-31"},
        headers=owner,
    )
    assert overlap.status_code == 422


def test_posting_blocked_in_locked_period(client: TestClient, org_id: uuid.UUID) -> None:
    owner, cid, acc = _setup(client, org_id)
    pid = client.post(
        f"/v1/companies/{cid}/periods",
        json={"fiscal_year": 2026, "starts_on": "2026-01-01", "ends_on": "2026-12-31"},
        headers=owner,
    ).json()["id"]
    # Draft within the period BEFORE locking.
    jid = _draft(client, cid, owner, acc, "2026-06-15")
    client.post(f"/v1/companies/{cid}/periods/{pid}/status", json={"status": "locked"}, headers=owner)
    # Posting into the now-locked period is a 409.
    resp = client.post(f"/v1/companies/{cid}/journals/{jid}/post", headers=owner)
    assert resp.status_code == 409
    assert "locked" in resp.json()["detail"].lower()


def test_posting_allowed_outside_any_period(client: TestClient, org_id: uuid.UUID) -> None:
    owner, cid, acc = _setup(client, org_id)
    # A date with no covering period posts fine.
    jid = _draft(client, cid, owner, acc, "2030-03-03")
    assert client.post(f"/v1/companies/{cid}/journals/{jid}/post", headers=owner).status_code == 200


def test_bookkeeper_cannot_manage_periods(client: TestClient, org_id: uuid.UUID) -> None:
    owner, cid, _ = _setup(client, org_id)
    _register(client, org_id, "book@example.com")
    client.post(f"/v1/companies/{cid}/members", json={"email": "book@example.com", "role": "bookkeeper"}, headers=owner)
    book = _auth(client, "book@example.com")
    # Bookkeeper can read periods but not create them (accountant+).
    assert client.get(f"/v1/companies/{cid}/periods", headers=book).status_code == 200
    resp = client.post(
        f"/v1/companies/{cid}/periods",
        json={"fiscal_year": 2026, "starts_on": "2026-01-01", "ends_on": "2026-12-31"},
        headers=book,
    )
    assert resp.status_code == 403
