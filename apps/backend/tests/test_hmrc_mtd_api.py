"""HTTP-level tests for HMRC MTD: connect, obligations, submit (mock client)."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session
from tests.helpers import auth_headers as _auth
from tests.helpers import register_user as _register

from ledgerline_backend.dependencies import get_hmrc_client
from ledgerline_backend.models import Company, Organisation
from ledgerline_backend.services.hmrc_client import (
    HmrcError,
    HmrcToken,
    NineBoxReturn,
    VatObligation,
    VatSubmissionReceipt,
)


class FakeHmrcClient:
    """In-memory HMRC client capturing calls, used in place of the real one."""

    def __init__(self, *, fail_submit: bool = False) -> None:
        self.fail_submit = fail_submit
        self.submitted: NineBoxReturn | None = None

    def exchange_code(self, *, code: str) -> HmrcToken:
        return HmrcToken(access_token=f"token-for-{code}", refresh_token="r", expires_in=3600)

    def list_obligations(
        self, *, access_token: str, vrn: str, from_date: str, to_date: str
    ) -> list[VatObligation]:
        return [
            VatObligation(
                period_key="18A1",
                start="2026-01-01",
                end="2026-03-31",
                due="2026-05-07",
                status="O",
                received=None,
            )
        ]

    def submit_return(
        self, *, access_token: str, vrn: str, ret: NineBoxReturn
    ) -> VatSubmissionReceipt:
        if self.fail_submit:
            raise HmrcError("HMRC rejected the return")
        self.submitted = ret
        return VatSubmissionReceipt(
            form_bundle_number="ABC-123456789",
            charge_ref_number="XQ12345",
            processing_date="2026-04-07T12:00:00.000Z",
            payment_indicator="DD",
        )


@pytest.fixture
def fake_client() -> FakeHmrcClient:
    return FakeHmrcClient()


@pytest.fixture
def org_id(app_engine: Engine) -> uuid.UUID:
    with Session(app_engine) as db:
        org = Organisation(name="Org", kind="business")
        db.add(org)
        db.commit()
        return org.id


def _use_fake(client: TestClient, fake: FakeHmrcClient) -> None:
    client.app.dependency_overrides[get_hmrc_client] = lambda: fake


def _company_with_vrn(
    client: TestClient, org_id: uuid.UUID, app_engine: Engine, *, vrn: str | None = "GB123456789"
) -> tuple[dict[str, str], str]:
    _register(client, org_id, "owner@example.com")
    owner = _auth(client, "owner@example.com")
    cid = client.post("/v1/companies", json={"name": "Co"}, headers=owner).json()["id"]
    if vrn is not None:
        with Session(app_engine) as db:
            company = db.get(Company, uuid.UUID(cid))
            assert company is not None
            company.vat_registration_no = vrn
            db.commit()
    return owner, cid


def _finalise_a_return(client: TestClient, cid: str, owner: dict[str, str]) -> str:
    # A VAT-coded sale so the boxes are non-zero, then finalise the period.
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
        json={"journal_date": "2026-02-15", "lines": [
            {"account_id": acc["1200"], "debit_minor": 120000},
            {"account_id": acc["4000"], "credit_minor": 100000, "vat_code": "SR", "vat_minor": 20000},
            {"account_id": acc["2200"], "credit_minor": 20000},
        ]},
        headers=owner,
    ).json()["id"]
    client.post(f"/v1/companies/{cid}/journals/{jid}/post", headers=owner)
    return client.post(
        f"/v1/companies/{cid}/vat-submissions",
        json={"period_start": "2026-01-01", "period_end": "2026-03-31", "reference": "R1"},
        headers=owner,
    ).json()["id"]


def test_connect_and_status(client: TestClient, org_id: uuid.UUID, app_engine: Engine, fake_client: FakeHmrcClient) -> None:
    _use_fake(client, fake_client)
    owner, cid = _company_with_vrn(client, org_id, app_engine)

    before = client.get(f"/v1/companies/{cid}/hmrc/status", headers=owner)
    assert before.status_code == 200
    assert before.json()["connected"] is False

    exch = client.post(f"/v1/companies/{cid}/hmrc/exchange", json={"code": "auth-code"}, headers=owner)
    assert exch.status_code == 204

    after = client.get(f"/v1/companies/{cid}/hmrc/status", headers=owner)
    assert after.json()["connected"] is True


def test_obligations(client: TestClient, org_id: uuid.UUID, app_engine: Engine, fake_client: FakeHmrcClient) -> None:
    _use_fake(client, fake_client)
    owner, cid = _company_with_vrn(client, org_id, app_engine)
    client.post(f"/v1/companies/{cid}/hmrc/exchange", json={"code": "c"}, headers=owner)

    resp = client.get(
        f"/v1/companies/{cid}/hmrc/obligations",
        params={"from_date": "2026-01-01", "to_date": "2026-12-31"},
        headers=owner,
    )
    assert resp.status_code == 200
    assert resp.json()[0]["period_key"] == "18A1"


def test_obligations_require_connection(client: TestClient, org_id: uuid.UUID, app_engine: Engine, fake_client: FakeHmrcClient) -> None:
    _use_fake(client, fake_client)
    owner, cid = _company_with_vrn(client, org_id, app_engine)
    resp = client.get(
        f"/v1/companies/{cid}/hmrc/obligations",
        params={"from_date": "2026-01-01", "to_date": "2026-12-31"},
        headers=owner,
    )
    assert resp.status_code == 409  # not connected


def test_submit_to_hmrc_stores_receipt(client: TestClient, org_id: uuid.UUID, app_engine: Engine, fake_client: FakeHmrcClient) -> None:
    _use_fake(client, fake_client)
    owner, cid = _company_with_vrn(client, org_id, app_engine)
    client.post(f"/v1/companies/{cid}/hmrc/exchange", json={"code": "c"}, headers=owner)
    submission_id = _finalise_a_return(client, cid, owner)

    resp = client.post(
        f"/v1/companies/{cid}/hmrc/submit",
        json={"submission_id": submission_id, "period_key": "18A1"},
        headers=owner,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["form_bundle_number"] == "ABC-123456789"
    assert body["charge_ref_number"] == "XQ12345"
    # The 9 boxes reached HMRC (output VAT box 1 = 200.00).
    assert fake_client.submitted is not None
    assert fake_client.submitted.box1_minor == 20000

    # The submission now records the HMRC receipt.
    subs = client.get(f"/v1/companies/{cid}/vat-submissions", headers=owner).json()
    assert subs[0]["reference"] == "R1"

    # Re-submitting the same return is rejected.
    again = client.post(
        f"/v1/companies/{cid}/hmrc/submit",
        json={"submission_id": submission_id, "period_key": "18A1"},
        headers=owner,
    )
    assert again.status_code == 409


def test_submit_no_vrn_rejected(client: TestClient, org_id: uuid.UUID, app_engine: Engine, fake_client: FakeHmrcClient) -> None:
    _use_fake(client, fake_client)
    owner, cid = _company_with_vrn(client, org_id, app_engine, vrn=None)
    client.post(f"/v1/companies/{cid}/hmrc/exchange", json={"code": "c"}, headers=owner)
    submission_id = _finalise_a_return(client, cid, owner)
    resp = client.post(
        f"/v1/companies/{cid}/hmrc/submit",
        json={"submission_id": submission_id, "period_key": "18A1"},
        headers=owner,
    )
    assert resp.status_code == 422  # no VAT registration number


def test_submit_hmrc_error_marks_submission(client: TestClient, org_id: uuid.UUID, app_engine: Engine) -> None:
    fake = FakeHmrcClient(fail_submit=True)
    _use_fake(client, fake)
    owner, cid = _company_with_vrn(client, org_id, app_engine)
    client.post(f"/v1/companies/{cid}/hmrc/exchange", json={"code": "c"}, headers=owner)
    submission_id = _finalise_a_return(client, cid, owner)
    resp = client.post(
        f"/v1/companies/{cid}/hmrc/submit",
        json={"submission_id": submission_id, "period_key": "18A1"},
        headers=owner,
    )
    assert resp.status_code == 502  # HMRC rejected -> bad gateway
