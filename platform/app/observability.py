"""Request metrics, the structured access log, and GET /metrics (P0-13, docs/adr/0019).

Order of the middleware, outermost first:
    RequestContextMiddleware (app/hardening.py: request ID, security headers)
      -> ObservabilityMiddleware (this file: times the request, counts it, logs it)
        -> CORS (SDK paths only) -> BodyLimit -> the application

The access log line holds: method, route template, path, status, duration, the error code if the
request failed, and the IDs of the partner, API key and session when the request was authenticated.
It never holds headers, query strings, bodies, tokens or network addresses.
"""
from __future__ import annotations

import hmac
import logging
import time

from fastapi import FastAPI, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.exceptions import HTTPException

from app import metrics
from app.config import Settings
from app.tracing import setup_tracing

access_log = logging.getLogger("certivo.access")
log = logging.getLogger("certivo.observability")

_QUIET_ROUTES = frozenset({"/healthz", "/metrics"})  # probes and scrapes would drown the real traffic
_MAX_PATH_LOGGED = 200


def _route_template(scope) -> str:
    """The route as written in the code (/v1/policies/{policy_id}), never the raw path: the raw path
    holds IDs and would create a new metric series for every one of them."""
    route = scope.get("route")
    return getattr(route, "path", None) or "unmatched"


class ObservabilityMiddleware:
    def __init__(self, app, settings: Settings):
        self.app, self.settings = app, settings

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        started = time.perf_counter()
        status: int | None = None

        async def send_and_note_status(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        metrics.HTTP_IN_PROGRESS.inc()
        try:
            await self.app(scope, receive, send_and_note_status)
        except Exception:
            status = 500  # the error handler (app/errors.py) answers with a 500 after this
            raise
        finally:
            metrics.HTTP_IN_PROGRESS.dec()
            duration = time.perf_counter() - started
            final_status = status if status is not None else 499  # the client went away first
            route = _route_template(scope)
            method = scope.get("method", "")
            metrics.record_request(method, route, final_status, duration)
            self._log(scope, method, route, final_status, duration)

    def _log(self, scope, method: str, route: str, status: int, duration_s: float) -> None:
        if route in _QUIET_ROUTES and status < 500:
            return
        state = scope.get("state") or {}
        fields = {
            "method": metrics.method_label(method),
            "route": route,
            "path": scope.get("path", "")[:_MAX_PATH_LOGGED],
            "status": status,
            "duration_ms": round(duration_s * 1000, 1),
        }
        for name in ("error_code", "partner_id", "api_key_id", "session_id"):
            if state.get(name):
                fields[name] = state[name]
        access_log.log(logging.ERROR if status >= 500 else logging.INFO, "request", extra=fields)


def _presented_token(request: Request) -> str:
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    return token.strip() if scheme.lower() == "bearer" else ""


def install_observability(app: FastAPI, settings: Settings) -> None:
    """Adds /metrics (when allowed), the build-info metric, and tracing (when switched on)."""
    metrics.BUILD_INFO.labels(version=app.version, env=settings.env).set(1)

    if settings.metrics_enabled:
        if settings.metrics_token or settings.env == "dev":
            expected = (settings.metrics_token or "").encode()

            @app.get("/metrics", include_in_schema=False)
            def metrics_endpoint(request: Request) -> Response:
                # Only the monitoring system may read this: it shows traffic volumes and error rates.
                if expected and not hmac.compare_digest(_presented_token(request).encode(), expected):
                    metrics.record_auth_failure("metrics_token")
                    # A plain standard 401, not a partner-API error code: /metrics is for the monitoring
                    # system and is deliberately outside the partner error catalogue (spec 01).
                    raise HTTPException(401, "A valid metrics token is required",
                                        headers={"WWW-Authenticate": "Bearer"})
                return Response(generate_latest(metrics.REGISTRY), media_type=CONTENT_TYPE_LATEST)
        else:
            log.warning("/metrics is NOT served: set CERTIVO_METRICS_TOKEN to enable it outside dev "
                        "(it is never served to unauthenticated callers outside dev)")

    if setup_tracing(app, settings):
        log.info("tracing is on", extra={"service": settings.tracing_service_name})
