"""HTTP-level tests for the workbook (spreadsheet) endpoints."""

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


def test_load_creates_default_workbook(client: TestClient, org_id: uuid.UUID) -> None:
    _register(client, org_id, "owner@example.com")
    owner = _auth(client, "owner@example.com")
    cid = _company(client, owner)
    resp = client.get(f"/v1/companies/{cid}/workbook", headers=owner)
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["sheets"]) == 1
    assert body["sheets"][0]["name"] == "Sheet1"


def test_save_and_reload(client: TestClient, org_id: uuid.UUID) -> None:
    _register(client, org_id, "owner@example.com")
    owner = _auth(client, "owner@example.com")
    cid = _company(client, owner)

    saved = client.put(
        f"/v1/companies/{cid}/workbook",
        json={
            "sheets": [
                {"name": "Receipts", "cells": [["Date", "Amount"], ["2026-06-27", "100.00"]]},
                {"name": "Payments", "cells": [["Date", "Amount"]]},
            ]
        },
        headers=owner,
    )
    assert saved.status_code == 200
    assert [s["name"] for s in saved.json()["sheets"]] == ["Receipts", "Payments"]

    reloaded = client.get(f"/v1/companies/{cid}/workbook", headers=owner).json()
    assert reloaded["sheets"][0]["cells"][1] == ["2026-06-27", "100.00"]


def test_save_requires_write_role(client: TestClient, org_id: uuid.UUID) -> None:
    _register(client, org_id, "owner@example.com")
    _register(client, org_id, "viewer@example.com")
    owner = _auth(client, "owner@example.com")
    cid = _company(client, owner)
    client.post(
        f"/v1/companies/{cid}/members",
        json={"email": "viewer@example.com", "role": "readonly"},
        headers=owner,
    )
    viewer = _auth(client, "viewer@example.com")
    # Readonly can load...
    assert client.get(f"/v1/companies/{cid}/workbook", headers=viewer).status_code == 200
    # ...but not save.
    resp = client.put(
        f"/v1/companies/{cid}/workbook",
        json={"sheets": [{"name": "X", "cells": []}]},
        headers=viewer,
    )
    assert resp.status_code == 403


def test_save_rejects_duplicate_names(client: TestClient, org_id: uuid.UUID) -> None:
    _register(client, org_id, "owner@example.com")
    owner = _auth(client, "owner@example.com")
    cid = _company(client, owner)
    resp = client.put(
        f"/v1/companies/{cid}/workbook",
        json={"sheets": [{"name": "A", "cells": []}, {"name": "A", "cells": []}]},
        headers=owner,
    )
    assert resp.status_code == 422


def test_non_member_cannot_access_workbook(client: TestClient, org_id: uuid.UUID) -> None:
    _register(client, org_id, "owner@example.com")
    _register(client, org_id, "stranger@example.com")
    owner = _auth(client, "owner@example.com")
    cid = _company(client, owner)
    stranger = _auth(client, "stranger@example.com")
    assert client.get(f"/v1/companies/{cid}/workbook", headers=stranger).status_code == 404
