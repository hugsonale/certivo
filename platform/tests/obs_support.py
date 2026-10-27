"""Shared helpers for the P0-13 tests (not a test file)."""
from __future__ import annotations

import io
import json
import logging
from contextlib import contextmanager

from fastapi import FastAPI

from app.config import Settings
from app.errors import ApiError, install_error_handling
from app.hardening import RequestContextMiddleware
from app.logging_setup import JsonFormatter
from app.observability import ObservabilityMiddleware, install_observability

# Obviously fake credentials shaped like ours, for proving they never reach a log line.
FAKE_API_KEY = "cvk_" + "A1b2C3d4" * 5
FAKE_SDK_TOKEN = "skt_" + "Z9y8X7w6" * 5


@contextmanager
def capture_logs(level: int = logging.INFO):
    """Collect every log line written inside the block, already parsed from JSON."""
    buffer = io.StringIO()
    handler = logging.StreamHandler(buffer)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(lambda record: record.name.startswith("certivo"))  # not the test client's own chatter
    root = logging.getLogger()
    previous_level = root.level
    root.addHandler(handler)
    root.setLevel(level)
    try:
        yield lambda: [json.loads(line) for line in buffer.getvalue().splitlines() if line.strip()]
    finally:
        root.removeHandler(handler)
        root.setLevel(previous_level)


def make_mini_app(**overrides) -> FastAPI:
    """A tiny app with the real request pipeline (request ID, metrics, access log, error handling)
    and a few routes that misbehave on purpose. Needs no database."""
    settings = Settings(_env_file=None, **overrides)
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings = settings
    install_error_handling(app)

    @app.get("/v1/things/{thing_id}")
    def get_thing(thing_id: str):
        return {"id": thing_id}

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    @app.get("/refused")
    def refused():
        raise ApiError(409, "seq_conflict", "A different packet already used this seq")

    @app.get("/boom")
    def boom():
        raise RuntimeError(f"database said no while using {FAKE_SDK_TOKEN}")

    install_observability(app, settings)
    app.add_middleware(ObservabilityMiddleware, settings=settings)
    app.add_middleware(RequestContextMiddleware, settings=settings)
    return app
