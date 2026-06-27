"""HTTP-level tests for the bank reconciliation endpoints."""

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


def _setup_with_posted_lines(client: TestClient, org_id: uuid.UUID) -> tuple[dict[str, str], str, str]:
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
    bank = client.post(
        f"/v1/companies/{cid}/bank-accounts",
        json={"name": "Current", "gl_account_id": acc["1200"]},
        headers=owner,
    ).json()["id"]
    client.post(
        f"/v1/companies/{cid}/bank-accounts/{bank}/import",
        json={"lines": [
            {"line_date": "2026-06-27", "description": "SALE A", "money_in_minor": 10000},
            {"line_date": "2026-06-27", "description": "SALE B", "money_in_minor": 25000},
        ]},
        headers=owner,
    )
    for line in client.get(f"/v1/companies/{cid}/bank-accounts/{bank}/lines", headers=owner).json():
        client.post(
            f"/v1/companies/{cid}/bank-accounts/{bank}/lines/{line['id']}/post",
            json={"contra_account_id": acc["4000"]},
            headers=owner,
        )
    return owner, cid, bank


def test_list_and_reconcile_line(client: TestClient, org_id: uuid.UUID) -> None:
    owner, cid, bank = _setup_with_posted_lines(client, org_id)
    lines = client.get(f"/v1/companies/{cid}/bank-accounts/{bank}/reconciliation", headers=owner)
    assert lines.status_code == 200
    assert len(lines.json()) == 2
    assert all(not line["reconciled"] for line in lines.json())

    target = lines.json()[0]
    resp = client.post(
        f"/v1/companies/{cid}/bank-accounts/{bank}/reconciliation/{target['journal_line_id']}",
        json={"reconciled": True},
        headers=owner,
    )
    assert resp.status_code == 204

    after = client.get(f"/v1/companies/{cid}/bank-accounts/{bank}/reconciliation", headers=owner).json()
    reconciled = [line for line in after if line["reconciled"]]
    assert len(reconciled) == 1


def test_reconciliation_summary(client: TestClient, org_id: uuid.UUID) -> None:
    owner, cid, bank = _setup_with_posted_lines(client, org_id)
    target = client.get(f"/v1/companies/{cid}/bank-accounts/{bank}/reconciliation", headers=owner).json()[0]
    client.post(
        f"/v1/companies/{cid}/bank-accounts/{bank}/reconciliation/{target['journal_line_id']}",
        json={"reconciled": True},
        headers=owner,
    )
    # Statement balance == the one reconciled line -> difference zero.
    summary = client.get(
        f"/v1/companies/{cid}/bank-accounts/{bank}/reconciliation-summary",
        params={"statement_balance_minor": target["amount_minor"]},
        headers=owner,
    )
    assert summary.status_code == 200
    body = summary.json()
    assert body["ledger_balance_minor"] == 35000
    assert body["reconciled_balance_minor"] == target["amount_minor"]
    assert body["unreconciled_count"] == 1
    assert body["difference_minor"] == 0


def test_readonly_cannot_reconcile(client: TestClient, org_id: uuid.UUID) -> None:
    owner, cid, bank = _setup_with_posted_lines(client, org_id)
    _register(client, org_id, "v@example.com")
    client.post(
        f"/v1/companies/{cid}/members",
        json={"email": "v@example.com", "role": "readonly"},
        headers=owner,
    )
    viewer = _auth(client, "v@example.com")
    target = client.get(f"/v1/companies/{cid}/bank-accounts/{bank}/reconciliation", headers=owner).json()[0]
    # Readonly can view the reconciliation list...
    assert client.get(f"/v1/companies/{cid}/bank-accounts/{bank}/reconciliation", headers=viewer).status_code == 200
    # ...but cannot tick a line.
    resp = client.post(
        f"/v1/companies/{cid}/bank-accounts/{bank}/reconciliation/{target['journal_line_id']}",
        json={"reconciled": True},
        headers=viewer,
    )
    assert resp.status_code == 403
