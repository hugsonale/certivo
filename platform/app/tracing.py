"""Tracing hooks (P0-13, docs/adr/0019).

OFF by default. Nothing here is required to run the platform: the OpenTelemetry packages are listed in
requirements-otel.txt, not requirements.txt. With them installed but tracing not switched on, `span()`
costs next to nothing and records nothing.

    with span("sessions.ingest", {"via": "live"}):
        ...

To switch on:  pip install -r requirements-otel.txt   then set CERTIVO_TRACING_ENABLED=true and, to send
spans somewhere, CERTIVO_TRACING_OTLP_ENDPOINT (for example http://collector:4318/v1/traces).

Privacy rule for span attributes: counts, timings and fixed code words only. Never a token, a score
packet, a signature or anything about a person (docs/spec/base/08).
"""
from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

log = logging.getLogger("certivo.tracing")

try:  # the API package alone is tiny; without it every hook is a no-op
    from opentelemetry import trace as _otel_trace
except ImportError:  # pragma: no cover - exercised when the package is absent
    _otel_trace = None

_TRACER_NAME = "certivo.platform"
_provider = None  # set by setup_tracing; we hand it out ourselves instead of changing a process-wide global


@contextmanager
def span(name: str, attributes: dict[str, Any] | None = None) -> Iterator[None]:
    """A named step in a request. Does nothing unless tracing was switched on."""
    if _otel_trace is None:
        yield
        return
    source = _provider if _provider is not None else _otel_trace
    with source.get_tracer(_TRACER_NAME).start_as_current_span(name, attributes=attributes):
        yield


def setup_tracing(app, settings, exporter=None) -> bool:
    """Switch tracing on if the settings ask for it. Returns True if it is now on.

    `exporter` is for tests (an in-memory exporter). Normally spans go to the OTLP endpoint.
    A missing package is a startup error, not a silent skip: someone who turned tracing on wants it.
    """
    if not settings.tracing_enabled:
        return False
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor
    except ImportError as exc:
        raise RuntimeError(
            "CERTIVO_TRACING_ENABLED is true but the OpenTelemetry packages are not installed. "
            "Run: pip install -r requirements-otel.txt") from exc

    provider = TracerProvider(resource=Resource.create({"service.name": settings.tracing_service_name}))
    if exporter is not None:
        provider.add_span_processor(SimpleSpanProcessor(exporter))
    elif settings.tracing_otlp_endpoint:
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        except ImportError as exc:
            raise RuntimeError("CERTIVO_TRACING_OTLP_ENDPOINT is set but the OTLP exporter is not "
                               "installed. Run: pip install -r requirements-otel.txt") from exc
        provider.add_span_processor(BatchSpanProcessor(
            OTLPSpanExporter(endpoint=settings.tracing_otlp_endpoint)))
    else:
        log.warning("tracing is on but no CERTIVO_TRACING_OTLP_ENDPOINT is set: spans are created "
                    "but not sent anywhere")
    global _provider
    _provider = provider
    FastAPIInstrumentor.instrument_app(app, tracer_provider=provider,
                                       excluded_urls="healthz,metrics")
    return True
