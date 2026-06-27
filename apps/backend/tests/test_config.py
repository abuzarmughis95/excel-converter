"""Tests for environment-driven configuration."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from ledgerline_backend.config import Settings


def test_defaults_are_development() -> None:
    settings = Settings()
    assert settings.environment == "development"
    assert settings.is_production is False
    assert settings.service_name == "ledgerline-backend"


def test_production_flag() -> None:
    settings = Settings(environment="production", jwt_secret="a-strong-production-secret")
    assert settings.is_production is True


def test_production_rejects_default_jwt_secret() -> None:
    with pytest.raises(ValidationError):
        Settings(environment="production")


def test_settings_are_frozen() -> None:
    """Settings must be immutable once loaded (no runtime mutation of config)."""
    settings = Settings()
    with pytest.raises(ValidationError):
        settings.environment = "production"  # type: ignore[misc]


def test_env_prefix_is_applied(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEDGERLINE_SERVICE_NAME", "custom-service")
    settings = Settings()
    assert settings.service_name == "custom-service"


def test_invalid_environment_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEDGERLINE_ENVIRONMENT", "banana")
    with pytest.raises(ValidationError):
        Settings()
