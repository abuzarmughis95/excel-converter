"""Tests for the liveness and version endpoints."""

from __future__ import annotations

from fastapi.testclient import TestClient

from ledgerline_backend import __version__


def test_health_returns_ok(client: TestClient) -> None:
    response = client.get("/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_response_is_json(client: TestClient) -> None:
    response = client.get("/v1/health")
    assert response.headers["content-type"].startswith("application/json")


def test_version_returns_metadata(client: TestClient) -> None:
    response = client.get("/v1/version")
    assert response.status_code == 200
    body = response.json()
    assert body["service"] == "ledgerline-backend"
    assert body["version"] == __version__
    assert body["environment"] == "test"


def test_version_does_not_leak_secrets(client: TestClient) -> None:
    """The version payload must contain only the three known public fields."""
    body = client.get("/v1/version").json()
    assert set(body.keys()) == {"service", "version", "environment"}


def test_unknown_route_returns_404(client: TestClient) -> None:
    assert client.get("/v1/does-not-exist").status_code == 404
