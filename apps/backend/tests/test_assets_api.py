"""HTTP-level tests for the fixed-asset register and depreciation."""

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


def _company_with_accounts(
    client: TestClient, org_id: uuid.UUID
) -> tuple[dict[str, str], str, dict[str, str]]:
    _register(client, org_id, "owner@example.com")
    owner = _auth(client, "owner@example.com")
    cid = client.post("/v1/companies", json={"name": "Co"}, headers=owner).json()["id"]
    acc = {}
    for code, name, atype in [
        ("0100", "Equipment", "asset"),
        ("0105", "Accumulated depreciation", "asset"),
        ("8000", "Depreciation expense", "expense"),
    ]:
        acc[code] = client.post(
            f"/v1/companies/{cid}/accounts",
            json={"code": code, "name": name, "account_type": atype},
            headers=owner,
        ).json()["id"]
    return owner, cid, acc


def _create_asset(client: TestClient, cid: str, owner: dict[str, str], acc: dict[str, str], **over: object) -> dict:
    body = {
        "name": "Laptop",
        "acquired_on": "2026-01-01",
        "cost_minor": 120000,
        "residual_minor": 0,
        "method": "straight_line",
        "useful_life_periods": 12,
        "asset_account_id": acc["0100"],
        "accumulated_account_id": acc["0105"],
        "expense_account_id": acc["8000"],
        **over,
    }
    return client.post(f"/v1/companies/{cid}/fixed-assets", json=body, headers=owner)


def test_create_and_list_asset_with_nbv(client: TestClient, org_id: uuid.UUID) -> None:
    owner, cid, acc = _company_with_accounts(client, org_id)
    created = _create_asset(client, cid, owner, acc)
    assert created.status_code == 201
    body = created.json()
    assert body["net_book_value_minor"] == 120000  # nothing depreciated yet
    assert body["accumulated_depreciation_minor"] == 0

    listed = client.get(f"/v1/companies/{cid}/fixed-assets", headers=owner)
    assert listed.status_code == 200
    assert len(listed.json()) == 1


def test_run_depreciation_posts_journal_and_reduces_nbv(client: TestClient, org_id: uuid.UUID) -> None:
    owner, cid, acc = _company_with_accounts(client, org_id)
    asset_id = _create_asset(client, cid, owner, acc).json()["id"]

    run = client.post(
        f"/v1/companies/{cid}/fixed-assets/{asset_id}/depreciate",
        json={"on_date": "2026-01-31"},
        headers=owner,
    )
    assert run.status_code == 200
    body = run.json()
    assert body["charge_minor"] == 10000  # 1200.00 / 12
    assert body["journal_id"] is not None

    # The asset's NBV dropped and a posted depreciation journal exists.
    asset = client.get(f"/v1/companies/{cid}/fixed-assets", headers=owner).json()[0]
    assert asset["accumulated_depreciation_minor"] == 10000
    assert asset["net_book_value_minor"] == 110000

    # Trial balance reflects the posted Dr expense / Cr accumulated.
    tb = {r["account_code"]: (r["debit_minor"], r["credit_minor"]) for r in client.get(
        f"/v1/companies/{cid}/trial-balance", headers=owner
    ).json()}
    assert tb["8000"] == (10000, 0)  # depreciation expense
    assert tb["0105"] == (0, 10000)  # accumulated depreciation (credit)


def test_depreciation_stops_when_fully_depreciated(client: TestClient, org_id: uuid.UUID) -> None:
    owner, cid, acc = _company_with_accounts(client, org_id)
    # 2 periods of useful life so we exhaust quickly.
    asset_id = _create_asset(
        client, cid, owner, acc, cost_minor=20000, useful_life_periods=2
    ).json()["id"]
    for _ in range(2):
        client.post(
            f"/v1/companies/{cid}/fixed-assets/{asset_id}/depreciate",
            json={"on_date": "2026-02-28"},
            headers=owner,
        )
    # Third run: nothing left to depreciate -> charge 0, no journal.
    third = client.post(
        f"/v1/companies/{cid}/fixed-assets/{asset_id}/depreciate",
        json={"on_date": "2026-03-31"},
        headers=owner,
    )
    assert third.status_code == 200
    assert third.json()["charge_minor"] == 0
    assert third.json()["journal_id"] is None
    asset = client.get(f"/v1/companies/{cid}/fixed-assets", headers=owner).json()[0]
    assert asset["net_book_value_minor"] == 0


def test_reducing_balance_asset(client: TestClient, org_id: uuid.UUID) -> None:
    owner, cid, acc = _company_with_accounts(client, org_id)
    asset_id = _create_asset(
        client, cid, owner, acc,
        method="reducing_balance", useful_life_periods=None, rate_percent=25,
    ).json()["id"]
    run = client.post(
        f"/v1/companies/{cid}/fixed-assets/{asset_id}/depreciate",
        json={"on_date": "2026-01-31"},
        headers=owner,
    )
    assert run.json()["charge_minor"] == 30000  # 25% of 1200.00


def test_invalid_residual_rejected(client: TestClient, org_id: uuid.UUID) -> None:
    owner, cid, acc = _company_with_accounts(client, org_id)
    resp = _create_asset(client, cid, owner, acc, residual_minor=200000)  # residual > cost
    assert resp.status_code == 422


def test_unknown_method_rejected(client: TestClient, org_id: uuid.UUID) -> None:
    owner, cid, acc = _company_with_accounts(client, org_id)
    resp = _create_asset(client, cid, owner, acc, method="sum_of_years")
    assert resp.status_code == 422


def test_assets_require_membership(client: TestClient, org_id: uuid.UUID) -> None:
    owner, cid, _ = _company_with_accounts(client, org_id)
    _register(client, org_id, "outsider@example.com")
    outsider = _auth(client, "outsider@example.com")
    assert client.get(f"/v1/companies/{cid}/fixed-assets", headers=outsider).status_code == 404
