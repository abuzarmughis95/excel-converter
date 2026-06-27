"""Application configuration, loaded from the environment (12-factor).

Secrets are never defaulted in code. Settings are validated by Pydantic at
startup so a misconfigured deployment fails fast rather than at first request.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["development", "test", "staging", "production"]

# Placeholder JWT secret used only for local development. Production startup is
# rejected if this value is still in place (see Settings.model_post_init). It is
# >=32 bytes to satisfy the HS256 minimum-key-length recommendation (RFC 7518).
_INSECURE_DEV_JWT_SECRET = "dev-insecure-change-me-0123456789-abcdef"  # noqa: S105 — sentinel


class Settings(BaseSettings):
    """Strongly-typed application settings sourced from environment variables."""

    model_config = SettingsConfigDict(
        env_prefix="LEDGERLINE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    environment: Environment = "development"
    """Deployment environment. Controls logging format and debug behaviour."""

    log_level: str = "INFO"
    """Root log level (DEBUG/INFO/WARNING/ERROR)."""

    log_json: bool = True
    """Emit structured JSON logs. Disabled locally for human-readable output."""

    service_name: str = "ledgerline-backend"
    """Identifier included in structured logs and the /version response."""

    cors_allowed_origins: tuple[str, ...] = Field(default=())
    """Explicit allow-list of browser origins. Empty in production by default."""

    database_url: str = "postgresql+psycopg://ledgerline:ledgerline_dev_only@localhost:5433/ledgerline"
    """SQLAlchemy URL for the platform PostgreSQL database.

    The default targets the local docker-compose Postgres (host port 5433 to
    avoid colliding with a native PostgreSQL install on 5432). In
    staging/production this MUST be supplied via the environment and point at a
    TLS-enforced instance.
    """

    jwt_secret: str = _INSECURE_DEV_JWT_SECRET
    """HMAC signing secret for access tokens.

    The default is intentionally insecure and is rejected in production by
    ``model_post_init`` so a real deployment cannot ship with it.
    """

    jwt_algorithm: str = "HS256"
    """JWT signing algorithm."""

    access_token_ttl_seconds: int = 900
    """Access-token lifetime (15 minutes). Kept short; refresh to extend."""

    refresh_token_ttl_seconds: int = 60 * 60 * 24 * 14
    """Refresh-token lifetime (14 days)."""

    max_failed_logins: int = 5
    """Failed attempts before an account is temporarily locked."""

    lockout_seconds: int = 900
    """Lockout duration after ``max_failed_logins`` failures (15 minutes)."""

    allow_open_registration: bool = True
    """Whether the public /auth/register endpoint is enabled.

    Open registration is convenient for development. In a real deployment users
    are typically provisioned via invitation/RBAC, so this can be disabled.
    """

    login_ip_max_attempts: int = 20
    """Max failed login attempts from one IP within the window before throttling."""

    login_ip_window_seconds: int = 300
    """Sliding window (seconds) for per-IP login throttling."""

    device_entitlement_ttl_seconds: int = 60 * 60 * 24 * 30
    """How long a registered device may operate offline before re-checking its
    entitlement (30 days)."""

    openai_api_key: str | None = None
    """OpenAI API key for document (bank statement) extraction. Loaded from the
    environment only; never hard-coded or committed. Extraction is unavailable
    when unset."""

    openai_model: str = "gpt-4o-mini"
    """OpenAI model used for statement extraction (vision-capable). Configurable
    so a newer model id can be supplied via the environment."""

    openai_max_upload_bytes: int = 15 * 1024 * 1024
    """Maximum accepted statement file size (15 MB)."""

    # -- HMRC Making Tax Digital (MTD) for VAT --
    hmrc_base_url: str = "https://test-api.service.hmrc.gov.uk"
    """HMRC API base URL. Defaults to the SANDBOX; set the production host
    (https://api.service.hmrc.gov.uk) only once an app has passed HMRC review."""

    hmrc_client_id: str | None = None
    """OAuth2 client id from the HMRC Developer Hub. MTD is unavailable when unset."""

    hmrc_client_secret: str | None = None
    """OAuth2 client secret from the HMRC Developer Hub (environment only)."""

    hmrc_redirect_uri: str = "http://localhost:8000/v1/hmrc/callback"
    """OAuth2 redirect URI registered with the HMRC app."""

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def ocr_enabled(self) -> bool:
        return self.openai_api_key is not None and self.openai_api_key.strip() != ""

    @property
    def hmrc_enabled(self) -> bool:
        return bool(
            self.hmrc_client_id
            and self.hmrc_client_id.strip()
            and self.hmrc_client_secret
            and self.hmrc_client_secret.strip()
        )

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    def model_post_init(self, _context: object) -> None:
        # Fail fast: never run production with the placeholder secret.
        if self.is_production and self.jwt_secret == _INSECURE_DEV_JWT_SECRET:
            msg = "LEDGERLINE_JWT_SECRET must be set to a strong value in production"
            raise ValueError(msg)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached, validated Settings instance."""
    return Settings()
