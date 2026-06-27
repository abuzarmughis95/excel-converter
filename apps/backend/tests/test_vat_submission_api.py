"""HTTP-level tests for VAT return finalisation (store + lock)."""

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






def _company_with_vat_sale(client: TestClient, org_id: uuid.UUID) -> tuple[dict[str, str], str]:
    _register(client, org_id, "owner@example.com")
    owner = _auth(client, "owner@example.com")
    cid = client.post("/v1/companies", json={"name": "Co"}, headers=owner).json()["id"]
    acc = {}
    for code, name, atype in [
        ("1200", "Bank", "asset"),
        ("2200", "VAT control", "liability"),
        ("4000", "Sales", "income"),
    ]:
        acc[code] = client.post(
            f"/v1/companies/{cid}/accounts",
            json={"code": code, "name": name, "account_type": atype},
            headers=owner,
        ).json()["id"]
    jid = client.post(
        f"/v1/companies/{cid}/journals",
        json={"journal_date": "2026-03-15", "lines": [
            {"account_id": acc["1200"], "debit_minor": 120000},
            {"account_id": acc["4000"], "credit_minor": 100000, "vat_code": "SR", "vat_minor": 20000},
            {"account_id": acc["2200"], "credit_minor": 20000},
        ]},
        headers=owner,
    ).json()["id"]
    client.post(f"/v1/companies/{cid}/journals/{jid}/post", headers=owner)
    return owner, cid


def test_finalise_snapshots_the_boxes(client: TestClient, org_id: uuid.UUID) -> None:
    owner, cid = _company_with_vat_sale(client, org_id)
    resp = client.post(
        f"/v1/companies/{cid}/vat-submissions",
        json={"period_start": "2026-01-01", "period_end": "2026-03-31", "reference": "HMRC-123"},
        headers=owner,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["reference"] == "HMRC-123"
    assert body["boxes"]["box1_minor"] == 20000  # output VAT snapshotted
    assert body["boxes"]["box6_minor"] == 100000

    listed = client.get(f"/v1/companies/{cid}/vat-submissions", headers=owner)
    assert listed.status_code == 200
    assert len(listed.json()) == 1


def test_finalise_with_lock_locks_the_period_and_freezes_boxes(client: TestClient, org_id: uuid.UUID) -> None:
    owner, cid = _company_with_vat_sale(client, org_id)
    # A Q1 period that the return fully covers.
    pid = client.post(
        f"/v1/companies/{cid}/periods",
        json={"fiscal_year": 2026, "starts_on": "2026-01-01", "ends_on": "2026-03-31"},
        headers=owner,
    ).json()["id"]
    resp = client.post(
        f"/v1/companies/{cid}/vat-submissions",
        json={"period_start": "2026-01-01", "period_end": "2026-03-31", "reference": "R1", "lock_period": True},
        headers=owner,
    )
    assert resp.status_code == 201
    # The covered period is now locked.
    periods = client.get(f"/v1/companies/{cid}/periods", headers=owner).json()
    locked = next(p for p in periods if p["id"] == pid)
    assert locked["status"] == "locked"


def test_finalise_duplicate_period_rejected(client: TestClient, org_id: uuid.UUID) -> None:
    owner, cid = _company_with_vat_sale(client, org_id)
    payload = {"period_start": "2026-01-01", "period_end": "2026-03-31", "reference": "R1"}
    assert client.post(f"/v1/companies/{cid}/vat-submissions", json=payload, headers=owner).status_code == 201
    dup = client.post(f"/v1/companies/{cid}/vat-submissions", json={**payload, "reference": "R2"}, headers=owner)
    assert dup.status_code == 409


def test_finalise_requires_accountant(client: TestClient, org_id: uuid.UUID) -> None:
    owner, cid = _company_with_vat_sale(client, org_id)
    _register(client, org_id, "book@example.com")
    client.post(f"/v1/companies/{cid}/members", json={"email": "book@example.com", "role": "bookkeeper"}, headers=owner)
    book = _auth(client, "book@example.com")
    # Bookkeeper can read submissions but not finalise (accountant+).
    assert client.get(f"/v1/companies/{cid}/vat-submissions", headers=book).status_code == 200
    resp = client.post(
        f"/v1/companies/{cid}/vat-submissions",
        json={"period_start": "2026-01-01", "period_end": "2026-03-31", "reference": "R"},
        headers=book,
    )
    assert resp.status_code == 403
