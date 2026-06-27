"""HTTP-level tests for the cashbook endpoints (bank accounts, import, post)."""

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
    accounts = {}
    for code, name, atype in [("1200", "Bank", "asset"), ("4000", "Sales", "income"), ("5000", "Costs", "expense")]:
        acc = client.post(
            f"/v1/companies/{cid}/accounts",
            json={"code": code, "name": name, "account_type": atype},
            headers=owner,
        ).json()
        accounts[code] = acc["id"]
    return owner, cid, accounts


def _bank(client: TestClient, owner: dict[str, str], cid: str, gl_id: str) -> str:
    return client.post(
        f"/v1/companies/{cid}/bank-accounts",
        json={"name": "Current", "gl_account_id": gl_id},
        headers=owner,
    ).json()["id"]


def test_create_and_list_bank_account(client: TestClient, org_id: uuid.UUID) -> None:
    owner, cid, acc = _setup(client, org_id)
    resp = client.post(
        f"/v1/companies/{cid}/bank-accounts",
        json={"name": "Current", "gl_account_id": acc["1200"]},
        headers=owner,
    )
    assert resp.status_code == 201, resp.text
    listed = client.get(f"/v1/companies/{cid}/bank-accounts", headers=owner)
    assert listed.status_code == 200
    assert len(listed.json()) == 1


def test_create_bank_rejects_bad_gl(client: TestClient, org_id: uuid.UUID) -> None:
    owner, cid, _ = _setup(client, org_id)
    resp = client.post(
        f"/v1/companies/{cid}/bank-accounts",
        json={"name": "X", "gl_account_id": str(uuid.uuid4())},
        headers=owner,
    )
    assert resp.status_code == 422


def test_import_lines_dedupe(client: TestClient, org_id: uuid.UUID) -> None:
    owner, cid, acc = _setup(client, org_id)
    bank = _bank(client, owner, cid, acc["1200"])
    body = {
        "lines": [
            {"line_date": "2026-06-27", "description": "SALES", "money_in_minor": 20000},
            {"line_date": "2026-06-27", "description": "RENT", "money_out_minor": 50000},
        ]
    }
    first = client.post(f"/v1/companies/{cid}/bank-accounts/{bank}/import", json=body, headers=owner)
    assert first.status_code == 200
    assert first.json() == {"imported": 2, "duplicates": 0}
    second = client.post(f"/v1/companies/{cid}/bank-accounts/{bank}/import", json=body, headers=owner)
    assert second.json() == {"imported": 0, "duplicates": 2}


def test_post_line_flows_to_trial_balance(client: TestClient, org_id: uuid.UUID) -> None:
    owner, cid, acc = _setup(client, org_id)
    bank = _bank(client, owner, cid, acc["1200"])
    client.post(
        f"/v1/companies/{cid}/bank-accounts/{bank}/import",
        json={"lines": [{"line_date": "2026-06-27", "description": "SALES", "money_in_minor": 20000}]},
        headers=owner,
    )
    line_id = client.get(f"/v1/companies/{cid}/bank-accounts/{bank}/lines", headers=owner).json()[0]["id"]

    posted = client.post(
        f"/v1/companies/{cid}/bank-accounts/{bank}/lines/{line_id}/post",
        json={"contra_account_id": acc["4000"]},
        headers=owner,
    )
    assert posted.status_code == 200
    assert "journal_id" in posted.json()

    tb = {r["account_code"]: (r["debit_minor"], r["credit_minor"])
          for r in client.get(f"/v1/companies/{cid}/trial-balance", headers=owner).json()}
    assert tb["1200"] == (20000, 0)
    assert tb["4000"] == (0, 20000)

    # The line now shows as posted.
    line = client.get(f"/v1/companies/{cid}/bank-accounts/{bank}/lines", headers=owner).json()[0]
    assert line["is_posted"] is True


def test_post_line_twice_409(client: TestClient, org_id: uuid.UUID) -> None:
    owner, cid, acc = _setup(client, org_id)
    bank = _bank(client, owner, cid, acc["1200"])
    client.post(
        f"/v1/companies/{cid}/bank-accounts/{bank}/import",
        json={"lines": [{"line_date": "2026-06-27", "description": "SALES", "money_in_minor": 100}]},
        headers=owner,
    )
    line_id = client.get(f"/v1/companies/{cid}/bank-accounts/{bank}/lines", headers=owner).json()[0]["id"]
    client.post(
        f"/v1/companies/{cid}/bank-accounts/{bank}/lines/{line_id}/post",
        json={"contra_account_id": acc["4000"]},
        headers=owner,
    )
    again = client.post(
        f"/v1/companies/{cid}/bank-accounts/{bank}/lines/{line_id}/post",
        json={"contra_account_id": acc["4000"]},
        headers=owner,
    )
    assert again.status_code == 409


def test_readonly_cannot_create_bank(client: TestClient, org_id: uuid.UUID) -> None:
    owner, cid, acc = _setup(client, org_id)
    _register(client, org_id, "v@example.com")
    client.post(
        f"/v1/companies/{cid}/members",
        json={"email": "v@example.com", "role": "readonly"},
        headers=owner,
    )
    viewer = _auth(client, "v@example.com")
    resp = client.post(
        f"/v1/companies/{cid}/bank-accounts",
        json={"name": "X", "gl_account_id": acc["1200"]},
        headers=viewer,
    )
    assert resp.status_code == 403


def test_non_member_404(client: TestClient, org_id: uuid.UUID) -> None:
    owner, cid, _ = _setup(client, org_id)
    _register(client, org_id, "s@example.com")
    stranger = _auth(client, "s@example.com")
    assert client.get(f"/v1/companies/{cid}/bank-accounts", headers=stranger).status_code == 404
