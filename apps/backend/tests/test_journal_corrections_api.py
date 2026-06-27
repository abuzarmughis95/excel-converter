"""HTTP-level tests for journal corrections: unpost and reverse."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session
from tests.helpers import auth_headers as _auth
from tests.helpers import register_user as _register

from ledgerline_backend.models import Organisation


@pytest.fixture
def org_id(app_engine: Engine) -> uuid.UUID:
    with Session(app_engine) as db:
        org = Organisation(name="Org", kind="business")
        db.add(org)
        db.commit()
        return org.id






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


def _post_journal(client: TestClient, cid: str, owner: dict[str, str], acc: dict[str, str]) -> str:
    jid = client.post(
        f"/v1/companies/{cid}/journals",
        json={"journal_date": "2026-06-27", "reference": "INV-1", "lines": [
            {"account_id": acc["1200"], "debit_minor": 10000},
            {"account_id": acc["4000"], "credit_minor": 10000},
        ]},
        headers=owner,
    ).json()["id"]
    client.post(f"/v1/companies/{cid}/journals/{jid}/post", headers=owner)
    return jid


def _trial_balance(client: TestClient, cid: str, owner: dict[str, str]) -> dict[str, tuple[int, int]]:
    rows = client.get(f"/v1/companies/{cid}/trial-balance", headers=owner).json()
    return {r["account_code"]: (r["debit_minor"], r["credit_minor"]) for r in rows}


def _all_zero(tb: dict[str, tuple[int, int]]) -> bool:
    """True if every account nets to zero (rows may still be present)."""
    return all(debit == 0 and credit == 0 for debit, credit in tb.values())


def test_unpost_requires_reason(client: TestClient, org_id: uuid.UUID) -> None:
    owner, cid, acc = _setup(client, org_id)
    jid = _post_journal(client, cid, owner, acc)
    bad = client.post(f"/v1/companies/{cid}/journals/{jid}/unpost", json={"reason": ""}, headers=owner)
    assert bad.status_code == 422


def test_unpost_removes_from_trial_balance(client: TestClient, org_id: uuid.UUID) -> None:
    owner, cid, acc = _setup(client, org_id)
    jid = _post_journal(client, cid, owner, acc)
    assert _trial_balance(client, cid, owner)  # has rows while posted
    resp = client.post(f"/v1/companies/{cid}/journals/{jid}/unpost", json={"reason": "wrong amount"}, headers=owner)
    assert resp.status_code == 200
    assert resp.json()["is_posted"] is False
    # After unposting, the entry no longer affects the trial balance.
    assert _all_zero(_trial_balance(client, cid, owner))


def test_reverse_creates_mirror_and_nets_to_zero(client: TestClient, org_id: uuid.UUID) -> None:
    owner, cid, acc = _setup(client, org_id)
    jid = _post_journal(client, cid, owner, acc)
    resp = client.post(
        f"/v1/companies/{cid}/journals/{jid}/reverse",
        json={"reason": "duplicate"},
        headers=owner,
    )
    assert resp.status_code == 201
    reversal = resp.json()
    assert reversal["journal_type"] == "reversal"
    assert reversal["is_posted"] is True
    # The reversal mirrors the original: debit and credit are swapped.
    bank_line = next(line for line in reversal["lines"] if line["account_code"] == "1200")
    assert bank_line["credit_minor"] == 10000
    assert bank_line["debit_minor"] == 0
    # Original + reversal net to zero.
    assert _all_zero(_trial_balance(client, cid, owner))


def test_reverse_requires_posted_journal(client: TestClient, org_id: uuid.UUID) -> None:
    owner, cid, acc = _setup(client, org_id)
    # A draft (unposted) journal cannot be reversed.
    jid = client.post(
        f"/v1/companies/{cid}/journals",
        json={"journal_date": "2026-06-27", "lines": [
            {"account_id": acc["1200"], "debit_minor": 10000},
            {"account_id": acc["4000"], "credit_minor": 10000},
        ]},
        headers=owner,
    ).json()["id"]
    resp = client.post(f"/v1/companies/{cid}/journals/{jid}/reverse", json={"reason": "x"}, headers=owner)
    assert resp.status_code == 409


def test_reverse_into_open_period_when_original_is_locked(client: TestClient, org_id: uuid.UUID) -> None:
    owner, cid, acc = _setup(client, org_id)
    jid = _post_journal(client, cid, owner, acc)  # dated 2026-06-27
    # Lock the 2026 period.
    pid = client.post(
        f"/v1/companies/{cid}/periods",
        json={"fiscal_year": 2026, "starts_on": "2026-01-01", "ends_on": "2026-12-31"},
        headers=owner,
    ).json()["id"]
    client.post(f"/v1/companies/{cid}/periods/{pid}/status", json={"status": "locked"}, headers=owner)
    # Reversing into the SAME locked date is blocked (409)...
    blocked = client.post(f"/v1/companies/{cid}/journals/{jid}/reverse", json={"reason": "fix"}, headers=owner)
    assert blocked.status_code == 409
    # ...but reversing into an open date succeeds.
    ok = client.post(
        f"/v1/companies/{cid}/journals/{jid}/reverse",
        json={"reason": "fix", "reversal_date": "2027-01-05"},
        headers=owner,
    )
    assert ok.status_code == 201
