"""HTTP-level tests for the bank-statement extraction endpoint."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from ledgerline_backend.app import create_app
from ledgerline_backend.config import Settings
from ledgerline_backend.models import Organisation

SAMPLE: dict[str, Any] = {
    "currency": "GBP",
    "summary": {
        "account_name": "ACME LTD",
        "account_number": "12345678",
        "sort_code": "12-34-56",
        "period_start": "2026-06-01",
        "period_end": "2026-06-30",
        "opening_balance": 1000.00,
        "closing_balance": 1150.00,
    },
    "lines": [
        {"date": "2026-06-02", "description": "CARD PAYMENT", "money_out": 50.00, "money_in": None, "balance": 950.00},
        {"date": "2026-06-10", "description": "SALES", "money_out": None, "money_in": 200.00, "balance": 1150.00},
    ],
}


class _FakeClient:
    def extract(self, *, pdf_bytes: bytes, model: str) -> dict[str, Any]:
        return SAMPLE


@pytest.fixture
def org_id(app_engine: Engine) -> uuid.UUID:
    with Session(app_engine) as db:
        org = Organisation(name="Org", kind="business")
        db.add(org)
        db.commit()
        return org.id


@pytest.fixture
def client_with_ocr(app_engine: Engine) -> Iterator[TestClient]:
    """App with a fake statement client injected (no real OpenAI call).

    ``_env_file=None`` prevents a developer's local .env (which may hold a real
    key) from leaking into the test; the fake client is always used here anyway.
    """
    settings = Settings(
        environment="test", log_json=False, openai_api_key="test-key", _env_file=None
    )
    app = create_app(settings, engine=app_engine)
    app.state.statement_client = _FakeClient()
    with TestClient(app) as c:
        yield c


@pytest.fixture
def client_no_ocr(app_engine: Engine) -> Iterator[TestClient]:
    """App with no API key configured (extraction unavailable).

    ``_env_file=None`` ensures a local .env key does not leak in, so the 503
    "not configured" path is exercised deterministically.
    """
    settings = Settings(
        environment="test", log_json=False, openai_api_key=None, _env_file=None
    )
    app = create_app(settings, engine=app_engine)
    with TestClient(app) as c:
        yield c


def _setup(client: TestClient, org_id: uuid.UUID) -> tuple[dict[str, str], str]:
    client.post(
        "/v1/auth/register",
        json={"org_id": str(org_id), "email": "o@example.com", "display_name": "O", "password": "password123"},
    )
    login = client.post("/v1/auth/login", json={"email": "o@example.com", "password": "password123"}).json()
    headers = {"Authorization": f"Bearer {login['access_token']}"}
    cid = client.post("/v1/companies", json={"name": "Co"}, headers=headers).json()["id"]
    return headers, cid


def test_extract_returns_structured_statement(
    client_with_ocr: TestClient, org_id: uuid.UUID
) -> None:
    headers, cid = _setup(client_with_ocr, org_id)
    resp = client_with_ocr.post(
        f"/v1/companies/{cid}/statements/extract",
        files={"file": ("statement.pdf", b"%PDF-1.4 fake bytes", "application/pdf")},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["reconciled"] is True
    assert body["summary"]["account_number"] == "12345678"
    assert body["summary"]["opening_balance_minor"] == 100000
    assert len(body["lines"]) == 2
    assert body["lines"][0]["money_out_minor"] == 5000


def test_extract_requires_auth(client_with_ocr: TestClient, org_id: uuid.UUID) -> None:
    # No auth header.
    resp = client_with_ocr.post(
        f"/v1/companies/{uuid.uuid4()}/statements/extract",
        files={"file": ("s.pdf", b"x", "application/pdf")},
    )
    assert resp.status_code == 401


def test_extract_rejects_non_pdf(client_with_ocr: TestClient, org_id: uuid.UUID) -> None:
    headers, cid = _setup(client_with_ocr, org_id)
    resp = client_with_ocr.post(
        f"/v1/companies/{cid}/statements/extract",
        files={"file": ("s.txt", b"hello", "text/plain")},
        headers=headers,
    )
    assert resp.status_code == 415


def test_extract_rejects_empty_file(client_with_ocr: TestClient, org_id: uuid.UUID) -> None:
    headers, cid = _setup(client_with_ocr, org_id)
    resp = client_with_ocr.post(
        f"/v1/companies/{cid}/statements/extract",
        files={"file": ("s.pdf", b"", "application/pdf")},
        headers=headers,
    )
    assert resp.status_code == 422


def test_extract_503_when_not_configured(client_no_ocr: TestClient, org_id: uuid.UUID) -> None:
    headers, cid = _setup(client_no_ocr, org_id)
    resp = client_no_ocr.post(
        f"/v1/companies/{cid}/statements/extract",
        files={"file": ("s.pdf", b"%PDF-1.4", "application/pdf")},
        headers=headers,
    )
    assert resp.status_code == 503


def test_readonly_cannot_extract(client_with_ocr: TestClient, org_id: uuid.UUID) -> None:
    headers, cid = _setup(client_with_ocr, org_id)
    client_with_ocr.post(
        "/v1/auth/register",
        json={"org_id": str(org_id), "email": "v@example.com", "display_name": "V", "password": "password123"},
    )
    client_with_ocr.post(
        f"/v1/companies/{cid}/members",
        json={"email": "v@example.com", "role": "readonly"},
        headers=headers,
    )
    login = client_with_ocr.post(
        "/v1/auth/login", json={"email": "v@example.com", "password": "password123"}
    ).json()
    viewer = {"Authorization": f"Bearer {login['access_token']}"}
    resp = client_with_ocr.post(
        f"/v1/companies/{cid}/statements/extract",
        files={"file": ("s.pdf", b"%PDF-1.4", "application/pdf")},
        headers=viewer,
    )
    assert resp.status_code == 403
