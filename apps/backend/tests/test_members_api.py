"""HTTP-level tests for company member-management endpoints + RBAC."""

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






def _company(client: TestClient, headers: dict[str, str]) -> str:
    return client.post("/v1/companies", json={"name": "Co"}, headers=headers).json()["id"]


def test_owner_can_add_and_list_members(client: TestClient, org_id: uuid.UUID) -> None:
    _register(client, org_id, "owner@example.com")
    _register(client, org_id, "bk@example.com")
    owner = _auth(client, "owner@example.com")
    company_id = _company(client, owner)

    add = client.post(
        f"/v1/companies/{company_id}/members",
        json={"email": "bk@example.com", "role": "bookkeeper"},
        headers=owner,
    )
    assert add.status_code == 201
    assert add.json()["role"] == "bookkeeper"

    members = client.get(f"/v1/companies/{company_id}/members", headers=owner)
    assert members.status_code == 200
    assert len(members.json()) == 2


def test_non_owner_cannot_manage_members(client: TestClient, org_id: uuid.UUID) -> None:
    _register(client, org_id, "owner@example.com")
    _register(client, org_id, "bk@example.com")
    owner = _auth(client, "owner@example.com")
    company_id = _company(client, owner)
    client.post(
        f"/v1/companies/{company_id}/members",
        json={"email": "bk@example.com", "role": "bookkeeper"},
        headers=owner,
    )

    bk = _auth(client, "bk@example.com")
    # A bookkeeper is a member but not an owner: listing members is forbidden (403).
    resp = client.get(f"/v1/companies/{company_id}/members", headers=bk)
    assert resp.status_code == 403


def test_non_member_gets_404_not_403(client: TestClient, org_id: uuid.UUID) -> None:
    _register(client, org_id, "owner@example.com")
    _register(client, org_id, "stranger@example.com")
    owner = _auth(client, "owner@example.com")
    company_id = _company(client, owner)

    stranger = _auth(client, "stranger@example.com")
    resp = client.get(f"/v1/companies/{company_id}/members", headers=stranger)
    # Leak-safe: a non-member cannot tell the company exists.
    assert resp.status_code == 404


def test_add_unknown_email_is_404(client: TestClient, org_id: uuid.UUID) -> None:
    _register(client, org_id, "owner@example.com")
    owner = _auth(client, "owner@example.com")
    company_id = _company(client, owner)
    resp = client.post(
        f"/v1/companies/{company_id}/members",
        json={"email": "ghost@example.com", "role": "readonly"},
        headers=owner,
    )
    assert resp.status_code == 404


def test_update_member_role(client: TestClient, org_id: uuid.UUID) -> None:
    _register(client, org_id, "owner@example.com")
    _register(client, org_id, "m@example.com")
    owner = _auth(client, "owner@example.com")
    company_id = _company(client, owner)
    added = client.post(
        f"/v1/companies/{company_id}/members",
        json={"email": "m@example.com", "role": "readonly"},
        headers=owner,
    ).json()

    resp = client.patch(
        f"/v1/companies/{company_id}/members/{added['user_id']}",
        json={"role": "accountant"},
        headers=owner,
    )
    assert resp.status_code == 200
    assert resp.json()["role"] == "accountant"


def test_cannot_remove_last_owner_via_api(client: TestClient, org_id: uuid.UUID) -> None:
    _register(client, org_id, "owner@example.com")
    owner = _auth(client, "owner@example.com")
    company_id = _company(client, owner)
    me = client.get("/v1/auth/me", headers=owner).json()

    resp = client.request(
        "DELETE", f"/v1/companies/{company_id}/members/{me['id']}", headers=owner
    )
    assert resp.status_code == 409


def test_remove_member(client: TestClient, org_id: uuid.UUID) -> None:
    _register(client, org_id, "owner@example.com")
    _register(client, org_id, "m@example.com")
    owner = _auth(client, "owner@example.com")
    company_id = _company(client, owner)
    added = client.post(
        f"/v1/companies/{company_id}/members",
        json={"email": "m@example.com", "role": "readonly"},
        headers=owner,
    ).json()

    resp = client.request(
        "DELETE", f"/v1/companies/{company_id}/members/{added['user_id']}", headers=owner
    )
    assert resp.status_code == 204
    members = client.get(f"/v1/companies/{company_id}/members", headers=owner).json()
    assert len(members) == 1
