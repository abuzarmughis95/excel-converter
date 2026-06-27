"""HTTP-level tests for journals + trial balance (incl. engine validation, RBAC)."""

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


def _capital_company(client: TestClient, org_id: uuid.UUID) -> tuple[dict[str, str], str, dict[str, str]]:
    """A company with capital + sale + cost posted (profit of 700.00)."""
    _register(client, org_id, "owner@example.com")
    owner = _auth(client, "owner@example.com")
    cid = client.post("/v1/companies", json={"name": "Co"}, headers=owner).json()["id"]
    acc = {}
    for code, name, atype in [
        ("1200", "Bank", "asset"),
        ("3000", "Capital", "equity"),
        ("4000", "Sales", "income"),
        ("5000", "Costs", "expense"),
    ]:
        acc[code] = client.post(
            f"/v1/companies/{cid}/accounts",
            json={"code": code, "name": name, "account_type": atype},
            headers=owner,
        ).json()["id"]

    def _post(lines: list[dict[str, object]]) -> None:
        j = client.post(
            f"/v1/companies/{cid}/journals",
            json={"journal_date": "2026-06-27", "lines": lines},
            headers=owner,
        ).json()
        client.post(f"/v1/companies/{cid}/journals/{j['id']}/post", headers=owner)

    _post([{"account_id": acc["1200"], "debit_minor": 50000}, {"account_id": acc["3000"], "credit_minor": 50000}])
    _post([{"account_id": acc["1200"], "debit_minor": 100000}, {"account_id": acc["4000"], "credit_minor": 100000}])
    _post([{"account_id": acc["5000"], "debit_minor": 30000}, {"account_id": acc["1200"], "credit_minor": 30000}])
    return owner, cid, acc


def test_profit_and_loss_report(client: TestClient, org_id: uuid.UUID) -> None:
    owner, cid, _ = _capital_company(client, org_id)
    resp = client.get(f"/v1/companies/{cid}/profit-and-loss", headers=owner)
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_income_minor"] == 100000
    assert body["total_expenses_minor"] == 30000
    assert body["net_profit_minor"] == 70000


def test_balance_sheet_report(client: TestClient, org_id: uuid.UUID) -> None:
    owner, cid, _ = _capital_company(client, org_id)
    resp = client.get(f"/v1/companies/{cid}/balance-sheet", headers=owner)
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_assets_minor"] == 120000
    assert body["total_liabilities_minor"] == 0
    # Equity = capital 50k + retained earnings (profit) 70k.
    assert body["total_equity_minor"] == 120000
    assert body["retained_earnings_minor"] == 70000
    # The accounting identity holds.
    assert body["total_assets_minor"] == body["total_liabilities_minor"] + body["total_equity_minor"]


def test_reports_require_membership(client: TestClient, org_id: uuid.UUID) -> None:
    owner, cid, _ = _capital_company(client, org_id)
    _register(client, org_id, "stranger@example.com")
    stranger = _auth(client, "stranger@example.com")
    assert client.get(f"/v1/companies/{cid}/profit-and-loss", headers=stranger).status_code == 404
    assert client.get(f"/v1/companies/{cid}/balance-sheet", headers=stranger).status_code == 404
