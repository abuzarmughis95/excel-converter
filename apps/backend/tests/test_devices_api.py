"""HTTP-level tests for the device registration endpoints."""

from __future__ import annotations

import base64
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from ledgerline_backend.models import Organisation

_PUBLIC_KEY_B64 = base64.b64encode(b"device-public-key-bytes").decode("ascii")


@pytest.fixture
def org_id(app_engine: Engine) -> uuid.UUID:
    with Session(app_engine) as db:
        org = Organisation(name="Org", kind="business")
        db.add(org)
        db.commit()
        return org.id


def _auth_header(client: TestClient, org_id: uuid.UUID, email: str = "dev@example.com") -> dict[str, str]:
    client.post(
        "/v1/auth/register",
        json={
            "org_id": str(org_id),
            "email": email,
            "display_name": "Dev",
            "password": "password123",
        },
    )
    login = client.post(
        "/v1/auth/login", json={"email": email, "password": "password123"}
    ).json()
    return {"Authorization": f"Bearer {login['access_token']}"}


def test_register_device_requires_auth(client: TestClient) -> None:
    resp = client.post(
        "/v1/auth/devices/register",
        json={"name": "Laptop", "platform": "win", "public_key_b64": _PUBLIC_KEY_B64},
    )
    assert resp.status_code == 401


def test_register_device_allocates_node_id(client: TestClient, org_id: uuid.UUID) -> None:
    headers = _auth_header(client, org_id)
    resp = client.post(
        "/v1/auth/devices/register",
        json={"name": "Laptop", "platform": "win", "public_key_b64": _PUBLIC_KEY_B64},
        headers=headers,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["node_id"] == 1
    assert "device_id" in body
    assert "entitlement_exp" in body


def test_second_device_gets_next_node_id(client: TestClient, org_id: uuid.UUID) -> None:
    headers = _auth_header(client, org_id)
    first = client.post(
        "/v1/auth/devices/register",
        json={"name": "A", "platform": "win", "public_key_b64": _PUBLIC_KEY_B64},
        headers=headers,
    ).json()
    second = client.post(
        "/v1/auth/devices/register",
        json={"name": "B", "platform": "mac", "public_key_b64": _PUBLIC_KEY_B64},
        headers=headers,
    ).json()
    assert first["node_id"] == 1
    assert second["node_id"] == 2


def test_register_rejects_bad_platform(client: TestClient, org_id: uuid.UUID) -> None:
    headers = _auth_header(client, org_id)
    resp = client.post(
        "/v1/auth/devices/register",
        json={"name": "X", "platform": "toaster", "public_key_b64": _PUBLIC_KEY_B64},
        headers=headers,
    )
    assert resp.status_code == 422


def test_register_rejects_invalid_base64(client: TestClient, org_id: uuid.UUID) -> None:
    headers = _auth_header(client, org_id)
    resp = client.post(
        "/v1/auth/devices/register",
        json={"name": "X", "platform": "win", "public_key_b64": "not-valid-base64!!!"},
        headers=headers,
    )
    assert resp.status_code == 422


def test_list_devices(client: TestClient, org_id: uuid.UUID) -> None:
    headers = _auth_header(client, org_id)
    client.post(
        "/v1/auth/devices/register",
        json={"name": "Laptop", "platform": "win", "public_key_b64": _PUBLIC_KEY_B64},
        headers=headers,
    )
    resp = client.get("/v1/auth/devices", headers=headers)
    assert resp.status_code == 200
    devices = resp.json()
    assert len(devices) == 1
    assert devices[0]["name"] == "Laptop"
    assert devices[0]["revoked"] is False


def test_revoke_device(client: TestClient, org_id: uuid.UUID) -> None:
    headers = _auth_header(client, org_id)
    reg = client.post(
        "/v1/auth/devices/register",
        json={"name": "Laptop", "platform": "win", "public_key_b64": _PUBLIC_KEY_B64},
        headers=headers,
    ).json()
    revoke = client.post(f"/v1/auth/devices/{reg['device_id']}/revoke", headers=headers)
    assert revoke.status_code == 204

    listed = client.get("/v1/auth/devices", headers=headers).json()
    assert listed[0]["revoked"] is True


def test_cannot_revoke_another_users_device(client: TestClient, org_id: uuid.UUID) -> None:
    owner = _auth_header(client, org_id, "owner@example.com")
    reg = client.post(
        "/v1/auth/devices/register",
        json={"name": "Owned", "platform": "win", "public_key_b64": _PUBLIC_KEY_B64},
        headers=owner,
    ).json()

    attacker = _auth_header(client, org_id, "attacker@example.com")
    resp = client.post(f"/v1/auth/devices/{reg['device_id']}/revoke", headers=attacker)
    # Leak-safe: report not-found rather than forbidden.
    assert resp.status_code == 404


def test_revoke_unknown_device_is_404(client: TestClient, org_id: uuid.UUID) -> None:
    headers = _auth_header(client, org_id)
    resp = client.post(f"/v1/auth/devices/{uuid.uuid4()}/revoke", headers=headers)
    assert resp.status_code == 404
