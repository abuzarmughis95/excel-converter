"""HTTP-level tests for the VAT return endpoint and VAT-coded journals."""

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


def _company_with_vat(client: TestClient, org_id: uuid.UUID) -> tuple[dict[str, str], str, dict[str, str]]:
    _register(client, org_id, "owner@example.com")
    owner = _auth(client, "owner@example.com")
    cid = client.post("/v1/companies", json={"name": "Co"}, headers=owner).json()["id"]
    acc = {}
    for code, name, atype in [
        ("1200", "Bank", "asset"),
        ("2200", "VAT control", "liability"),
        ("4000", "Sales", "income"),
        ("5000", "Purchases", "expense"),
    ]:
        acc[code] = client.post(
            f"/v1/companies/{cid}/accounts",
            json={"code": code, "name": name, "account_type": atype},
            headers=owner,
        ).json()["id"]
    return owner, cid, acc


def _post(client: TestClient, cid: str, owner: dict[str, str], lines: list[dict[str, object]]) -> int:
    created = client.post(
        f"/v1/companies/{cid}/journals",
        json={"journal_date": "2026-06-27", "lines": lines},
        headers=owner,
    )
    if created.status_code == 201:
        jid = created.json()["id"]
        client.post(f"/v1/companies/{cid}/journals/{jid}/post", headers=owner)
    return created.status_code


def test_vat_return_from_sale_and_purchase(client: TestClient, org_id: uuid.UUID) -> None:
    owner, cid, acc = _company_with_vat(client, org_id)
    # Sale: Dr bank 1200.00, Cr sales 1000.00 (VAT 200.00), Cr VAT control 200.00.
    assert _post(client, cid, owner, [
        {"account_id": acc["1200"], "debit_minor": 120000},
        {"account_id": acc["4000"], "credit_minor": 100000, "vat_code": "SR", "vat_minor": 20000},
        {"account_id": acc["2200"], "credit_minor": 20000},
    ]) == 201
    # Purchase: Dr purchases 500.00 (VAT 100.00), Dr VAT control 100.00, Cr bank 600.00.
    assert _post(client, cid, owner, [
        {"account_id": acc["5000"], "debit_minor": 50000, "vat_code": "SR", "vat_minor": 10000},
        {"account_id": acc["2200"], "debit_minor": 10000},
        {"account_id": acc["1200"], "credit_minor": 60000},
    ]) == 201

    vr = client.get(f"/v1/companies/{cid}/vat-return", headers=owner)
    assert vr.status_code == 200
    body = vr.json()
    assert body["box1_minor"] == 20000  # output VAT
    assert body["box4_minor"] == 10000  # input VAT
    assert body["box3_minor"] == 20000
    assert body["box5_minor"] == 10000  # net to pay
    assert body["box6_minor"] == 100000  # sales ex VAT
    assert body["box7_minor"] == 50000  # purchases ex VAT


def test_empty_vat_return_is_zero(client: TestClient, org_id: uuid.UUID) -> None:
    owner, cid, _ = _company_with_vat(client, org_id)
    body = client.get(f"/v1/companies/{cid}/vat-return", headers=owner).json()
    assert body["box1_minor"] == 0
    assert body["box5_minor"] == 0


def test_unknown_vat_code_rejected(client: TestClient, org_id: uuid.UUID) -> None:
    owner, cid, acc = _company_with_vat(client, org_id)
    resp = client.post(
        f"/v1/companies/{cid}/journals",
        json={"journal_date": "2026-06-27", "lines": [
            {"account_id": acc["4000"], "credit_minor": 100000, "vat_code": "BOGUS", "vat_minor": 20000},
            {"account_id": acc["1200"], "debit_minor": 100000},
        ]},
        headers=owner,
    )
    assert resp.status_code == 422


def test_vat_return_requires_membership(client: TestClient, org_id: uuid.UUID) -> None:
    owner, cid, _ = _company_with_vat(client, org_id)
    _register(client, org_id, "outsider@example.com")
    outsider = _auth(client, "outsider@example.com")
    # Non-member gets 404 (leak-safe), not 403.
    assert client.get(f"/v1/companies/{cid}/vat-return", headers=outsider).status_code == 404
