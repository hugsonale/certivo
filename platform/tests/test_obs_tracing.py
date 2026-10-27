"""Tracing hooks (P0-13): off by default, harmless when off, and working when switched on."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import tracing
from app.config import Settings


def test_a_span_is_harmless_when_tracing_is_off():
    with tracing.span("anything", {"via": "live"}):
        pass  # no exception, nothing recorded


def test_tracing_is_off_by_default():
    assert Settings(_env_file=None).tracing_enabled is False
    assert tracing.setup_tracing(FastAPI(), Settings(_env_file=None)) is False


def test_switching_tracing_on_without_the_packages_is_a_clear_startup_error(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def refuse(name, *args, **kwargs):
        if name.startswith("opentelemetry.sdk") or name.startswith("opentelemetry.instrumentation"):
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", refuse)
    with pytest.raises(RuntimeError, match="requirements-otel.txt"):
        tracing.setup_tracing(FastAPI(), Settings(_env_file=None, tracing_enabled=True))


def test_spans_and_log_correlation_work_when_switched_on():
    pytest.importorskip("opentelemetry.sdk")
    pytest.importorskip("opentelemetry.instrumentation.fastapi")
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    from tests.obs_support import capture_logs

    exporter = InMemorySpanExporter()
    app = FastAPI()

    @app.get("/work")
    def work():
        with tracing.span("sessions.ingest_score_event", {"via": "live"}):
            import logging
            logging.getLogger("certivo.test").info("inside the span")
        return {}

    settings = Settings(_env_file=None, tracing_enabled=True)
    try:
        assert tracing.setup_tracing(app, settings, exporter=exporter) is True
        with capture_logs() as lines:
            TestClient(app).get("/work")
        names = {s.name for s in exporter.get_finished_spans()}
        assert "sessions.ingest_score_event" in names
        inside = next(e for e in lines() if e["msg"] == "inside the span")
        assert len(inside["trace_id"]) == 32 and len(inside["span_id"]) == 16
    finally:
        tracing._provider = None
