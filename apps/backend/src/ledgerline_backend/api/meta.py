"""Service metadata endpoints: liveness and version.

These are intentionally unauthenticated and free of any tenant data so they can
be used by load balancers and uptime checks without leaking information.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ledgerline_backend import __version__
from ledgerline_backend.config import Settings
from ledgerline_backend.dependencies import get_app_settings

router = APIRouter(tags=["meta"])


class HealthResponse(BaseModel):
    """Liveness probe response."""

    status: str


class VersionResponse(BaseModel):
    """Build/version metadata response."""

    service: str
    version: str
    environment: str


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Liveness check. Returns 200 with a static body when the process is up."""
    return HealthResponse(status="ok")


@router.get("/version", response_model=VersionResponse)
def version(settings: Annotated[Settings, Depends(get_app_settings)]) -> VersionResponse:
    """Return service name, version, and environment (no secrets)."""
    return VersionResponse(
        service=settings.service_name,
        version=__version__,
        environment=settings.environment,
    )
