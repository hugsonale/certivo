from __future__ import annotations

from collections.abc import Callable

from fastapi import FastAPI

from app.admin import ensure_default_policy
from app.attestation import load_signer
from app.config import Settings
from app.db import assert_schema_current, make_engine, make_session_factory, upgrade_to_head
from app.errors import install_error_handling
from app.hardening import (
    CORS_ALLOW_HEADERS,
    CORS_EXPOSE_HEADERS,
    BodyLimitMiddleware,
    PathScopedCORS,
    RequestContextMiddleware,
)
from app.keyregistry import register_signing_key
from app.logging_setup import configure_logging
from app.observability import ObservabilityMiddleware, install_observability
from app.ratelimit import RateLimiter
from app.routers import api_keys, devices, meta, policies, sessions, webhooks
from app.secretbox import load_secretbox
from app.timeutil import now_ms


def create_app(settings: Settings | None = None, clock: Callable[[], int] | None = None) -> FastAPI:
    settings = settings or Settings()
    configure_logging(settings.log_level, settings.log_format)  # first, so startup problems are logged too
    engine = make_engine(settings.database_url, settings.db_statement_timeout_ms)
    docs = settings.docs_enabled
    app = FastAPI(
        title="Certivo Platform", version="0.1.0",
        docs_url="/docs" if docs else None,
        redoc_url="/redoc" if docs else None,
        openapi_url="/openapi.json" if docs else None,
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = make_session_factory(engine)
    app.state.clock = clock or now_ms
    app.state.limiter = RateLimiter(app.state.clock)
    app.state.signer = load_signer(settings)
    app.state.secretbox = load_secretbox(settings)  # fails at startup if the key is missing outside dev

    # The schema comes from migrations only. Dev may apply them automatically; every other
    # environment must have run `alembic upgrade head` already, or the app refuses to start.
    if settings.env == "dev" and settings.auto_migrate:
        upgrade_to_head(settings.database_url)
    assert_schema_current(engine)

    with app.state.session_factory() as db:
        ensure_default_policy(db)
        db.commit()
        register_signing_key(db, app.state.signer, app.state.clock())

    install_error_handling(app)
    app.include_router(meta.router)
    app.include_router(devices.router)
    app.include_router(api_keys.router)
    app.include_router(policies.router)
    app.include_router(sessions.router)
    app.include_router(webhooks.router)
    install_observability(app, settings)  # /metrics, build info, tracing (when switched on)

    # Middleware: the LAST one added is the OUTERMOST. Order seen by a request:
    # RequestContext (ID + security headers) -> Observability (metrics + access log)
    # -> CORS (SDK paths only) -> BodyLimit -> the app.
    app.add_middleware(BodyLimitMiddleware, max_bytes=settings.max_body_bytes,
                       read_timeout_s=settings.body_read_timeout_s)
    if settings.cors_origins:
        app.add_middleware(
            PathScopedCORS,
            allow_origins=settings.cors_origins,
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=CORS_ALLOW_HEADERS,
            expose_headers=CORS_EXPOSE_HEADERS,
            allow_credentials=False,
            max_age=600,
        )
    app.add_middleware(ObservabilityMiddleware, settings=settings)
    app.add_middleware(RequestContextMiddleware, settings=settings)
    return app
