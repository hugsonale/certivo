from __future__ import annotations

from collections.abc import Callable

from fastapi import FastAPI

from app.admin import ensure_default_policy
from app.attestation import load_signer
from app.config import Settings
from app.db import assert_schema_current, make_engine, make_session_factory, upgrade_to_head
from app.errors import install_error_handling
from app.routers import devices, meta, sessions
from app.timeutil import now_ms


def create_app(settings: Settings | None = None, clock: Callable[[], int] | None = None) -> FastAPI:
    settings = settings or Settings()
    engine = make_engine(settings.database_url)
    app = FastAPI(title="Certivo Platform", version="0.1.0")
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = make_session_factory(engine)
    app.state.clock = clock or now_ms
    app.state.signer = load_signer(settings)

    # The schema comes from migrations only. Dev may apply them automatically; every other
    # environment must have run `alembic upgrade head` already, or the app refuses to start.
    if settings.env == "dev" and settings.auto_migrate:
        upgrade_to_head(settings.database_url)
    assert_schema_current(engine)

    with app.state.session_factory() as db:
        ensure_default_policy(db)
        db.commit()

    install_error_handling(app)
    app.include_router(meta.router)
    app.include_router(devices.router)
    app.include_router(sessions.router)
    return app
