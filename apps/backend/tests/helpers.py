"""Shared helpers for API tests.

These wrap the register/login dance every company-scoped test repeats, so the
test files stay focused on the behaviour under test.
"""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

DEFAULT_PASSWORD = "password123"


def register_user(
    client: TestClient,
    org_id: uuid.UUID,
    email: str,
    *,
    display_name: str = "U",
    password: str = DEFAULT_PASSWORD,
) -> None:
    """Register a user in the given organisation."""
    client.post(
        "/v1/auth/register",
        json={
            "org_id": str(org_id),
            "email": email,
            "display_name": display_name,
            "password": password,
        },
    )


def auth_headers(
    client: TestClient, email: str, *, password: str = DEFAULT_PASSWORD
) -> dict[str, str]:
    """Log in and return the Bearer Authorization header."""
    login = client.post(
        "/v1/auth/login", json={"email": email, "password": password}
    ).json()
    return {"Authorization": f"Bearer {login['access_token']}"}


def register_and_auth(
    client: TestClient, org_id: uuid.UUID, email: str
) -> dict[str, str]:
    """Register a user and return their auth header in one step."""
    register_user(client, org_id, email)
    return auth_headers(client, email)
