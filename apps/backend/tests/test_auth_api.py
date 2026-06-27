"""HTTP-level tests for the authentication endpoints."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from ledgerline_backend.app import create_app
from ledgerline_backend.config import Settings
from ledgerline_backend.models import Organisation


@pytest.fixture
def org_id(app_engine: Engine) -> uuid.UUID:
    with Session(app_engine) as db:
        org = Organisation(name="Org", kind="business")
        db.add(org)
        db.commit()
        return org.id


def _register(client: TestClient, org_id: uuid.UUID, email: str = "user@example.com") -> None:
    resp = client.post(
        "/v1/auth/register",
        json={
            "org_id": str(org_id),
            "email": email,
            "display_name": "User",
            "password": "password123",
        },
    )
    assert resp.status_code == 201, resp.text


def test_register_returns_user_without_secrets(
    client: TestClient, org_id: uuid.UUID
) -> None:
    resp = client.post(
        "/v1/auth/register",
        json={
            "org_id": str(org_id),
            "email": "new@example.com",
            "display_name": "New",
            "password": "password123",
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["email"] == "new@example.com"
    assert set(body.keys()) == {"id", "email", "display_name", "status"}
    assert "password" not in body


def test_register_duplicate_email_conflicts(client: TestClient, org_id: uuid.UUID) -> None:
    _register(client, org_id, "dup@example.com")
    resp = client.post(
        "/v1/auth/register",
        json={
            "org_id": str(org_id),
            "email": "dup@example.com",
            "display_name": "Dup",
            "password": "password123",
        },
    )
    assert resp.status_code == 409


def test_login_returns_token_pair(client: TestClient, org_id: uuid.UUID) -> None:
    _register(client, org_id)
    resp = client.post(
        "/v1/auth/login",
        json={"email": "user@example.com", "password": "password123"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["refresh_token"]


def test_login_wrong_password_is_401(client: TestClient, org_id: uuid.UUID) -> None:
    _register(client, org_id)
    resp = client.post(
        "/v1/auth/login",
        json={"email": "user@example.com", "password": "wrong-password"},
    )
    assert resp.status_code == 401


def test_me_requires_token(client: TestClient) -> None:
    assert client.get("/v1/auth/me").status_code == 401


def test_me_returns_profile_with_token(client: TestClient, org_id: uuid.UUID) -> None:
    _register(client, org_id)
    login = client.post(
        "/v1/auth/login",
        json={"email": "user@example.com", "password": "password123"},
    ).json()
    resp = client.get(
        "/v1/auth/me",
        headers={"Authorization": f"Bearer {login['access_token']}"},
    )
    assert resp.status_code == 200
    assert resp.json()["email"] == "user@example.com"


def test_me_rejects_garbage_token(client: TestClient) -> None:
    resp = client.get("/v1/auth/me", headers={"Authorization": "Bearer not-a-token"})
    assert resp.status_code == 401


def test_refresh_rotates_token(client: TestClient, org_id: uuid.UUID) -> None:
    _register(client, org_id)
    login = client.post(
        "/v1/auth/login",
        json={"email": "user@example.com", "password": "password123"},
    ).json()

    refreshed = client.post(
        "/v1/auth/refresh",
        json={"refresh_token": login["refresh_token"]},
    )
    assert refreshed.status_code == 200
    assert refreshed.json()["refresh_token"] != login["refresh_token"]

    # Old refresh token is now invalid.
    reuse = client.post(
        "/v1/auth/refresh",
        json={"refresh_token": login["refresh_token"]},
    )
    assert reuse.status_code == 401


def test_logout_then_refresh_is_401(client: TestClient, org_id: uuid.UUID) -> None:
    _register(client, org_id)
    login = client.post(
        "/v1/auth/login",
        json={"email": "user@example.com", "password": "password123"},
    ).json()

    assert client.post(
        "/v1/auth/logout", json={"refresh_token": login["refresh_token"]}
    ).status_code == 204

    assert client.post(
        "/v1/auth/refresh", json={"refresh_token": login["refresh_token"]}
    ).status_code == 401


def test_account_lockout_returns_429(client: TestClient, org_id: uuid.UUID, settings) -> None:  # type: ignore[no-untyped-def]
    _register(client, org_id)
    for _ in range(settings.max_failed_logins):
        client.post(
            "/v1/auth/login",
            json={"email": "user@example.com", "password": "wrong"},
        )
    resp = client.post(
        "/v1/auth/login",
        json={"email": "user@example.com", "password": "password123"},
    )
    assert resp.status_code == 429


def test_register_unknown_org_is_422(client: TestClient) -> None:
    resp = client.post(
        "/v1/auth/register",
        json={
            "org_id": str(uuid.uuid4()),
            "email": "ghost@example.com",
            "display_name": "Ghost",
            "password": "password123",
        },
    )
    assert resp.status_code == 422


def test_login_response_includes_mfa_required(client: TestClient, org_id: uuid.UUID) -> None:
    _register(client, org_id)
    body = client.post(
        "/v1/auth/login",
        json={"email": "user@example.com", "password": "password123"},
    ).json()
    assert body["mfa_required"] is False


def test_registration_can_be_disabled(app_engine: Engine, org_id: uuid.UUID) -> None:
    settings = Settings(environment="test", log_json=False, allow_open_registration=False)
    app = create_app(settings, engine=app_engine)
    with TestClient(app) as client:
        resp = client.post(
            "/v1/auth/register",
            json={
                "org_id": str(org_id),
                "email": "blocked@example.com",
                "display_name": "Blocked",
                "password": "password123",
            },
        )
    assert resp.status_code == 403


def test_per_ip_throttle_blocks_after_window(app_engine: Engine, org_id: uuid.UUID) -> None:
    # A small IP budget so the test trips it quickly across distinct accounts.
    settings = Settings(
        environment="test",
        log_json=False,
        login_ip_max_attempts=3,
        login_ip_window_seconds=300,
        max_failed_logins=100,  # high, so per-account lockout doesn't fire first
    )
    app = create_app(settings, engine=app_engine)
    with TestClient(app) as client:
        # Each attempt targets a different (non-existent) account, so only the
        # per-IP limiter — not per-account lockout — can stop us.
        for i in range(settings.login_ip_max_attempts):
            r = client.post(
                "/v1/auth/login",
                json={"email": f"nobody{i}@example.com", "password": "wrong"},
            )
            assert r.status_code == 401
        blocked = client.post(
            "/v1/auth/login",
            json={"email": "nobody-final@example.com", "password": "wrong"},
        )
    assert blocked.status_code == 429
