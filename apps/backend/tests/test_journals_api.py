"""HTTP-level tests for journals + trial balance (incl. engine validation, RBAC)."""

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


def _setup_company_with_accounts(client: TestClient, org_id: uuid.UUID) -> tuple[dict[str, str], str, dict[str, str]]:
    _register(client, org_id, "owner@example.com")
    owner = _auth(client, "owner@example.com")
    cid = client.post("/v1/companies", json={"name": "Co"}, headers=owner).json()["id"]
    accounts = {}
    for code, name, atype in [
        ("1200", "Bank", "asset"),
        ("4000", "Sales", "income"),
        ("2200", "VAT", "liability"),
    ]:
        acc = client.post(
            f"/v1/companies/{cid}/accounts",
            json={"code": code, "name": name, "account_type": atype},
            headers=owner,
        ).json()
        accounts[code] = acc["id"]
    return owner, cid, accounts


def test_create_balanced_journal(client: TestClient, org_id: uuid.UUID) -> None:
    owner, cid, acc = _setup_company_with_accounts(client, org_id)
    resp = client.post(
        f"/v1/companies/{cid}/journals",
        json={
            "journal_date": "2026-06-27",
            "lines": [
                {"account_id": acc["1200"], "debit_minor": 12000},
                {"account_id": acc["4000"], "credit_minor": 12000},
            ],
        },
        headers=owner,
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["is_posted"] is False
    assert len(resp.json()["lines"]) == 2


def test_unbalanced_journal_is_422(client: TestClient, org_id: uuid.UUID) -> None:
    owner, cid, acc = _setup_company_with_accounts(client, org_id)
    resp = client.post(
        f"/v1/companies/{cid}/journals",
        json={
            "journal_date": "2026-06-27",
            "lines": [
                {"account_id": acc["1200"], "debit_minor": 12000},
                {"account_id": acc["4000"], "credit_minor": 11999},
            ],
        },
        headers=owner,
    )
    assert resp.status_code == 422
    assert "balance" in resp.json()["detail"].lower()


def test_post_and_trial_balance(client: TestClient, org_id: uuid.UUID) -> None:
    owner, cid, acc = _setup_company_with_accounts(client, org_id)
    journal = client.post(
        f"/v1/companies/{cid}/journals",
        json={
            "journal_date": "2026-06-27",
            "lines": [
                {"account_id": acc["1200"], "debit_minor": 12000},
                {"account_id": acc["4000"], "credit_minor": 10000},
                {"account_id": acc["2200"], "credit_minor": 2000},
            ],
        },
        headers=owner,
    ).json()

    # Trial balance is empty until posted.
    tb_before = client.get(f"/v1/companies/{cid}/trial-balance", headers=owner).json()
    assert all(r["debit_minor"] == 0 and r["credit_minor"] == 0 for r in tb_before)

    posted = client.post(f"/v1/companies/{cid}/journals/{journal['id']}/post", headers=owner)
    assert posted.status_code == 200
    assert posted.json()["is_posted"] is True

    tb = {r["account_code"]: (r["debit_minor"], r["credit_minor"])
          for r in client.get(f"/v1/companies/{cid}/trial-balance", headers=owner).json()}
    assert tb["1200"] == (12000, 0)
    assert tb["4000"] == (0, 10000)
    assert tb["2200"] == (0, 2000)


def test_unpost_journal(client: TestClient, org_id: uuid.UUID) -> None:
    owner, cid, acc = _setup_company_with_accounts(client, org_id)
    j = client.post(
        f"/v1/companies/{cid}/journals",
        json={
            "journal_date": "2026-06-27",
            "lines": [
                {"account_id": acc["1200"], "debit_minor": 5000},
                {"account_id": acc["4000"], "credit_minor": 5000},
            ],
        },
        headers=owner,
    ).json()
    client.post(f"/v1/companies/{cid}/journals/{j['id']}/post", headers=owner)
    resp = client.post(
        f"/v1/companies/{cid}/journals/{j['id']}/unpost",
        json={"reason": "data entry error"},
        headers=owner,
    )
    assert resp.status_code == 200
    assert resp.json()["is_posted"] is False


def test_cannot_post_twice_409(client: TestClient, org_id: uuid.UUID) -> None:
    owner, cid, acc = _setup_company_with_accounts(client, org_id)
    j = client.post(
        f"/v1/companies/{cid}/journals",
        json={
            "journal_date": "2026-06-27",
            "lines": [
                {"account_id": acc["1200"], "debit_minor": 100},
                {"account_id": acc["4000"], "credit_minor": 100},
            ],
        },
        headers=owner,
    ).json()
    client.post(f"/v1/companies/{cid}/journals/{j['id']}/post", headers=owner)
    again = client.post(f"/v1/companies/{cid}/journals/{j['id']}/post", headers=owner)
    assert again.status_code == 409


def test_readonly_cannot_create_journal(client: TestClient, org_id: uuid.UUID) -> None:
    owner, cid, acc = _setup_company_with_accounts(client, org_id)
    _register(client, org_id, "viewer@example.com")
    client.post(
        f"/v1/companies/{cid}/members",
        json={"email": "viewer@example.com", "role": "readonly"},
        headers=owner,
    )
    viewer = _auth(client, "viewer@example.com")
    # Readonly can read the trial balance...
    assert client.get(f"/v1/companies/{cid}/trial-balance", headers=viewer).status_code == 200
    # ...but cannot create a journal.
    resp = client.post(
        f"/v1/companies/{cid}/journals",
        json={
            "journal_date": "2026-06-27",
            "lines": [
                {"account_id": acc["1200"], "debit_minor": 100},
                {"account_id": acc["4000"], "credit_minor": 100},
            ],
        },
        headers=viewer,
    )
    assert resp.status_code == 403


def test_non_member_gets_404(client: TestClient, org_id: uuid.UUID) -> None:
    owner, cid, _ = _setup_company_with_accounts(client, org_id)
    _register(client, org_id, "stranger@example.com")
    stranger = _auth(client, "stranger@example.com")
    assert client.get(f"/v1/companies/{cid}/journals", headers=stranger).status_code == 404
