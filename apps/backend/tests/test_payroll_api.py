"""HTTP-level tests for payroll: employees, pay runs, payslips, wages journal."""

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
        ("7000", "Wages", "expense"),
        ("7010", "Employer NI", "expense"),
        ("2210", "PAYE/NI liability", "liability"),
        ("2220", "Net wages payable", "liability"),
    ]:
        acc[code] = client.post(
            f"/v1/companies/{cid}/accounts",
            json={"code": code, "name": name, "account_type": atype},
            headers=owner,
        ).json()["id"]
    return owner, cid, acc


def _add_employee(client: TestClient, cid: str, owner: dict[str, str], **over: object) -> dict:
    body = {"name": "Alice", "annual_salary_minor": 3600000, "tax_code": "1257L", **over}
    return client.post(f"/v1/companies/{cid}/payroll/employees", json=body, headers=owner)


def _run(client: TestClient, cid: str, owner: dict[str, str], acc: dict[str, str], label: str = "2026-06") -> dict:
    return client.post(
        f"/v1/companies/{cid}/payroll/runs",
        json={
            "period_label": label,
            "pay_date": "2026-06-28",
            "wages_account_id": acc["7000"],
            "employer_ni_account_id": acc["7010"],
            "liability_account_id": acc["2210"],
            "net_pay_account_id": acc["2220"],
        },
        headers=owner,
    )


def test_create_and_list_employees(client: TestClient, org_id: uuid.UUID) -> None:
    owner, cid, _ = _company_with_accounts(client, org_id)
    created = _add_employee(client, cid, owner)
    assert created.status_code == 201
    listed = client.get(f"/v1/companies/{cid}/payroll/employees", headers=owner)
    assert listed.status_code == 200
    assert len(listed.json()) == 1
    assert listed.json()[0]["name"] == "Alice"


def test_run_payroll_computes_and_posts_wages_journal(client: TestClient, org_id: uuid.UUID) -> None:
    owner, cid, acc = _company_with_accounts(client, org_id)
    # £36,000/year -> £3,000/month, 1257L, category A.
    _add_employee(client, cid, owner)

    run = _run(client, cid, owner, acc)
    assert run.status_code == 201
    body = run.json()
    assert len(body["payslips"]) == 1
    slip = body["payslips"][0]
    assert slip["gross_minor"] == 300000
    assert slip["income_tax_minor"] == 39050  # matches the engine
    assert slip["employee_ni_minor"] == 15620
    assert slip["employer_ni_minor"] == 38750
    assert slip["net_minor"] == 300000 - 39050 - 15620
    assert body["total_gross_minor"] == 300000

    # The wages journal balances and hits the right accounts.
    tb = {r["account_code"]: (r["debit_minor"], r["credit_minor"]) for r in client.get(
        f"/v1/companies/{cid}/trial-balance", headers=owner
    ).json()}
    assert tb["7000"] == (300000, 0)  # wages expense Dr gross
    assert tb["7010"] == (38750, 0)  # employer NI expense Dr
    # Liability Cr = tax + employee NI + employer NI.
    assert tb["2210"] == (0, 39050 + 15620 + 38750)
    assert tb["2220"] == (0, slip["net_minor"])  # net pay payable Cr


def test_payslips_listed(client: TestClient, org_id: uuid.UUID) -> None:
    owner, cid, acc = _company_with_accounts(client, org_id)
    _add_employee(client, cid, owner)
    _run(client, cid, owner, acc)
    slips = client.get(f"/v1/companies/{cid}/payroll/payslips", headers=owner)
    assert slips.status_code == 200
    assert len(slips.json()) == 1


def test_running_same_period_twice_rejected(client: TestClient, org_id: uuid.UUID) -> None:
    owner, cid, acc = _company_with_accounts(client, org_id)
    _add_employee(client, cid, owner)
    assert _run(client, cid, owner, acc).status_code == 201
    again = _run(client, cid, owner, acc)
    assert again.status_code == 409


def test_run_with_no_employees_rejected(client: TestClient, org_id: uuid.UUID) -> None:
    owner, cid, acc = _company_with_accounts(client, org_id)
    assert _run(client, cid, owner, acc).status_code == 422


def test_unknown_ni_category_rejected(client: TestClient, org_id: uuid.UUID) -> None:
    owner, cid, _ = _company_with_accounts(client, org_id)
    resp = _add_employee(client, cid, owner, ni_category="Z")
    assert resp.status_code == 422


def test_payroll_requires_membership(client: TestClient, org_id: uuid.UUID) -> None:
    owner, cid, _ = _company_with_accounts(client, org_id)
    _register(client, org_id, "outsider@example.com")
    outsider = _auth(client, "outsider@example.com")
    assert client.get(f"/v1/companies/{cid}/payroll/employees", headers=outsider).status_code == 404
