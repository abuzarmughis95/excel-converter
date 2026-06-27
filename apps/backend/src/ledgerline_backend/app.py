"""FastAPI application factory.

Using a factory (rather than a module-level global) keeps the app testable: each
test can build an isolated instance with overridden settings.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import Engine

from ledgerline_backend import __version__
from ledgerline_backend.api import (
    auth,
    cashbook,
    coa,
    companies,
    devices,
    journals,
    meta,
    statements,
    workbooks,
)
from ledgerline_backend.config import Settings, get_settings
from ledgerline_backend.db.session import create_db_engine, create_session_factory
from ledgerline_backend.logging import configure_logging, get_logger
from ledgerline_backend.security.rate_limit import SlidingWindowRateLimiter


def create_app(settings: Settings | None = None, *, engine: Engine | None = None) -> FastAPI:
    """Build and configure a FastAPI application instance.

    An ``engine`` may be supplied (e.g. by tests) to bind the app to a specific
    database; otherwise one is created from ``settings.database_url``.
    """
    settings = settings or get_settings()
    configure_logging(settings)
    log = get_logger(__name__)

    db_engine = engine or create_db_engine(settings.database_url)
    session_factory = create_session_factory(db_engine)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        log.info("service.startup", service=settings.service_name, env=settings.environment)
        yield
        log.info("service.shutdown", service=settings.service_name)

    app = FastAPI(
        title="Ledgerline API",
        version=__version__,
        description="Offline-first UK accounting & compliance platform — backend API.",
        lifespan=lifespan,
        # Disable interactive docs in production to reduce surface area.
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None if settings.is_production else "/redoc",
    )

    # Bind settings and the DB session factory to app state so request-scoped
    # dependencies resolve the configuration this instance was built with.
    app.state.settings = settings
    app.state.db_engine = db_engine
    app.state.session_factory = session_factory
    app.state.login_rate_limiter = SlidingWindowRateLimiter(
        max_events=settings.login_ip_max_attempts,
        window_seconds=settings.login_ip_window_seconds,
    )

    if settings.cors_allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.cors_allowed_origins),
            allow_credentials=True,
            allow_methods=["GET", "POST", "PATCH", "DELETE"],
            allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
        )

    app.include_router(meta.router, prefix="/v1")
    app.include_router(auth.router, prefix="/v1")
    app.include_router(devices.router, prefix="/v1")
    app.include_router(companies.router, prefix="/v1")
    app.include_router(coa.router, prefix="/v1")
    app.include_router(journals.router, prefix="/v1")
    app.include_router(workbooks.router, prefix="/v1")
    app.include_router(statements.router, prefix="/v1")
    app.include_router(cashbook.router, prefix="/v1")

    return app


app = create_app()
