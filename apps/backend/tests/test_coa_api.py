"""HTTP-level tests for the Chart of Accounts endpoints (incl. RBAC)."""

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


def _company(client: TestClient, headers: dict[str, str]) -> str:
    return client.post("/v1/companies", json={"name": "Co"}, headers=headers).json()["id"]


def test_create_and_list_accounts(client: TestClient, org_id: uuid.UUID) -> None:
    _register(client, org_id, "owner@example.com")
    owner = _auth(client, "owner@example.com")
    cid = _company(client, owner)

    resp = client.post(
        f"/v1/companies/{cid}/accounts",
        json={"code": "1200", "name": "Bank", "account_type": "asset"},
        headers=owner,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["normal_balance"] == "DR"  # derived from the engine

    listed = client.get(f"/v1/companies/{cid}/accounts", headers=owner)
    assert listed.status_code == 200
    assert len(listed.json()) == 1


def test_create_rejects_bad_type(client: TestClient, org_id: uuid.UUID) -> None:
    _register(client, org_id, "owner@example.com")
    owner = _auth(client, "owner@example.com")
    cid = _company(client, owner)
    resp = client.post(
        f"/v1/companies/{cid}/accounts",
        json={"code": "1", "name": "X", "account_type": "banana"},
        headers=owner,
    )
    assert resp.status_code == 422


def test_duplicate_code_conflicts(client: TestClient, org_id: uuid.UUID) -> None:
    _register(client, org_id, "owner@example.com")
    owner = _auth(client, "owner@example.com")
    cid = _company(client, owner)
    payload = {"code": "1200", "name": "Bank", "account_type": "asset"}
    client.post(f"/v1/companies/{cid}/accounts", json=payload, headers=owner)
    resp = client.post(f"/v1/companies/{cid}/accounts", json=payload, headers=owner)
    assert resp.status_code == 409


def test_readonly_member_cannot_create(client: TestClient, org_id: uuid.UUID) -> None:
    _register(client, org_id, "owner@example.com")
    _register(client, org_id, "viewer@example.com")
    owner = _auth(client, "owner@example.com")
    cid = _company(client, owner)
    # Add viewer as readonly.
    client.post(
        f"/v1/companies/{cid}/members",
        json={"email": "viewer@example.com", "role": "readonly"},
        headers=owner,
    )

    viewer = _auth(client, "viewer@example.com")
    # Readonly CAN list...
    assert client.get(f"/v1/companies/{cid}/accounts", headers=viewer).status_code == 200
    # ...but CANNOT create (needs bookkeeper+).
    resp = client.post(
        f"/v1/companies/{cid}/accounts",
        json={"code": "1200", "name": "Bank", "account_type": "asset"},
        headers=viewer,
    )
    assert resp.status_code == 403


def test_bookkeeper_can_create(client: TestClient, org_id: uuid.UUID) -> None:
    _register(client, org_id, "owner@example.com")
    _register(client, org_id, "bk@example.com")
    owner = _auth(client, "owner@example.com")
    cid = _company(client, owner)
    client.post(
        f"/v1/companies/{cid}/members",
        json={"email": "bk@example.com", "role": "bookkeeper"},
        headers=owner,
    )
    bk = _auth(client, "bk@example.com")
    resp = client.post(
        f"/v1/companies/{cid}/accounts",
        json={"code": "4000", "name": "Sales", "account_type": "income"},
        headers=bk,
    )
    assert resp.status_code == 201


def test_non_member_gets_404(client: TestClient, org_id: uuid.UUID) -> None:
    _register(client, org_id, "owner@example.com")
    _register(client, org_id, "stranger@example.com")
    owner = _auth(client, "owner@example.com")
    cid = _company(client, owner)

    stranger = _auth(client, "stranger@example.com")
    resp = client.get(f"/v1/companies/{cid}/accounts", headers=stranger)
    assert resp.status_code == 404  # leak-safe


def test_rename_and_deactivate(client: TestClient, org_id: uuid.UUID) -> None:
    _register(client, org_id, "owner@example.com")
    owner = _auth(client, "owner@example.com")
    cid = _company(client, owner)
    acc = client.post(
        f"/v1/companies/{cid}/accounts",
        json={"code": "1200", "name": "Bank", "account_type": "asset"},
        headers=owner,
    ).json()

    renamed = client.patch(
        f"/v1/companies/{cid}/accounts/{acc['id']}",
        json={"name": "Current Account"},
        headers=owner,
    )
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Current Account"

    deactivated = client.post(
        f"/v1/companies/{cid}/accounts/{acc['id']}/deactivate", headers=owner
    )
    assert deactivated.status_code == 200
    assert deactivated.json()["is_active"] is False

    # Filtered list excludes inactive.
    active_only = client.get(
        f"/v1/companies/{cid}/accounts?include_inactive=false", headers=owner
    ).json()
    assert active_only == []
