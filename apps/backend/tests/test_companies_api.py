"""HTTP-level tests for the company endpoints."""

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


def _auth(client: TestClient, org_id: uuid.UUID, email: str) -> dict[str, str]:
    client.post(
        "/v1/auth/register",
        json={
            "org_id": str(org_id),
            "email": email,
            "display_name": "U",
            "password": "password123",
        },
    )
    login = client.post("/v1/auth/login", json={"email": email, "password": "password123"}).json()
    return {"Authorization": f"Bearer {login['access_token']}"}


def test_create_company_requires_auth(client: TestClient) -> None:
    assert client.post("/v1/companies", json={"name": "X"}).status_code == 401


def test_create_and_list_company(client: TestClient, org_id: uuid.UUID) -> None:
    headers = _auth(client, org_id, "owner@example.com")
    created = client.post("/v1/companies", json={"name": "Acme Ltd"}, headers=headers)
    assert created.status_code == 201
    body = created.json()
    assert body["name"] == "Acme Ltd"
    assert body["role"] == "owner"
    assert body["base_currency"] == "GBP"

    listed = client.get("/v1/companies", headers=headers)
    assert listed.status_code == 200
    assert len(listed.json()) == 1


def test_create_rejects_bad_accounts_type(client: TestClient, org_id: uuid.UUID) -> None:
    headers = _auth(client, org_id, "owner@example.com")
    resp = client.post(
        "/v1/companies", json={"name": "X", "accounts_type": "banana"}, headers=headers
    )
    assert resp.status_code == 422


def test_companies_are_scoped_per_user(client: TestClient, org_id: uuid.UUID) -> None:
    owner = _auth(client, org_id, "owner@example.com")
    other = _auth(client, org_id, "other@example.com")
    client.post("/v1/companies", json={"name": "Owner Co"}, headers=owner)

    # The other user sees none of the owner's companies.
    assert client.get("/v1/companies", headers=other).json() == []


def test_get_company_by_member(client: TestClient, org_id: uuid.UUID) -> None:
    headers = _auth(client, org_id, "owner@example.com")
    created = client.post("/v1/companies", json={"name": "Acme"}, headers=headers).json()
    resp = client.get(f"/v1/companies/{created['id']}", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["id"] == created["id"]


def test_get_company_by_non_member_is_404(client: TestClient, org_id: uuid.UUID) -> None:
    owner = _auth(client, org_id, "owner@example.com")
    other = _auth(client, org_id, "other@example.com")
    created = client.post("/v1/companies", json={"name": "Acme"}, headers=owner).json()
    resp = client.get(f"/v1/companies/{created['id']}", headers=other)
    assert resp.status_code == 404


def test_update_company_by_owner(client: TestClient, org_id: uuid.UUID) -> None:
    headers = _auth(client, org_id, "owner@example.com")
    created = client.post("/v1/companies", json={"name": "Old"}, headers=headers).json()
    resp = client.patch(
        f"/v1/companies/{created['id']}",
        json={"name": "New", "vat_registration_no": "GB123456789"},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "New"
    assert resp.json()["vat_registration_no"] == "GB123456789"


def test_update_unknown_company_is_404(client: TestClient, org_id: uuid.UUID) -> None:
    headers = _auth(client, org_id, "owner@example.com")
    resp = client.patch(f"/v1/companies/{uuid.uuid4()}", json={"name": "x"}, headers=headers)
    assert resp.status_code == 404
