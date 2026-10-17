"""Request-pipeline protections: request ID, security headers, body size and slow-body limits, CORS.

Everything here is plain ASGI middleware so it runs for every request, including ones rejected before
they reach a route. Order, outermost first: RequestContext -> CORS (SDK paths only) -> BodyLimit.
"""
from __future__ import annotations

import asyncio
import uuid

from fastapi.responses import JSONResponse
from starlette.datastructures import MutableHeaders
from starlette.middleware.cors import CORSMiddleware

from app.config import Settings
from app.errors import HttpRejection, error_body

DOCS_PATHS = ("/docs", "/redoc", "/openapi.json")
# Browsers only ever call the SDK endpoints and the public-keys endpoint. The partner API (/v1/)
# is server-to-server and must never be opened to browser origins.
CORS_PATH_PREFIXES = ("/internal/v1/", "/.well-known/")
CORS_ALLOW_HEADERS = ["Authorization", "Content-Type", "Idempotency-Key",
                      "Certivo-SDK-Version", "Certivo-SDK-Platform"]
CORS_EXPOSE_HEADERS = ["X-Request-ID", "Retry-After", "RateLimit-Limit", "RateLimit-Remaining",
                       "RateLimit-Reset"]


def security_header_items(settings: Settings, path: str) -> list[tuple[str, str]]:
    items = [
        ("X-Content-Type-Options", "nosniff"),
        ("X-Frame-Options", "DENY"),
        ("Referrer-Policy", "no-referrer"),
        ("Cache-Control", "no-store"),  # responses can contain one-time secrets
    ]
    on_docs_page = settings.docs_enabled and path.startswith(DOCS_PATHS)
    if not on_docs_page:  # the interactive docs page needs scripts, so it gets no CSP
        items.append(("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'"))
    if settings.env != "dev":  # HSTS only means something over HTTPS
        items.append(("Strict-Transport-Security", "max-age=31536000; includeSubDomains"))
    return items


class RequestContextMiddleware:
    """Gives every request an ID and puts the ID and the security headers on every response."""

    def __init__(self, app, settings: Settings):
        self.app, self.settings = app, settings

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        request_id = f"req_{uuid.uuid4().hex[:16]}"
        scope.setdefault("state", {})["request_id"] = request_id
        path = scope["path"]

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["X-Request-ID"] = request_id
                for name, value in security_header_items(self.settings, path):
                    headers[name] = value
            await send(message)

        await self.app(scope, receive, send_with_headers)


class BodyLimitMiddleware:
    """Refuses oversized request bodies (413) and bodies that stall while arriving (408)."""

    def __init__(self, app, max_bytes: int, read_timeout_s: float):
        self.app, self.max_bytes, self.read_timeout_s = app, max_bytes, read_timeout_s

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        declared = _declared_length(scope)
        if declared is not None and declared > self.max_bytes:
            # Refuse immediately, without reading any of the body.
            request_id = scope.get("state", {}).get("request_id")
            body = error_body(request_id, "payload_too_large",
                              f"Request body is larger than {self.max_bytes} bytes")
            return await JSONResponse(body, status_code=413)(scope, receive, send)

        received = 0
        body_complete = False

        async def guarded_receive():
            nonlocal received, body_complete
            if body_complete:  # after the body, the app only waits for a disconnect: no timeout
                return await receive()
            try:
                message = await asyncio.wait_for(receive(), timeout=self.read_timeout_s)
            except asyncio.TimeoutError:
                raise HttpRejection(408, "request_timeout",
                                    "The request body was not received in time") from None
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise HttpRejection(413, "payload_too_large",
                                        f"Request body is larger than {self.max_bytes} bytes")
                body_complete = not message.get("more_body", False)
            return message

        await self.app(scope, guarded_receive, send)


def _declared_length(scope) -> int | None:
    for name, value in scope["headers"]:
        if name == b"content-length":
            try:
                return int(value)
            except ValueError:
                return None  # the HTTP server itself rejects a malformed Content-Length
    return None


class PathScopedCORS:
    """Applies Starlette's CORS handling only to the SDK paths."""

    def __init__(self, app, prefixes: tuple[str, ...] = CORS_PATH_PREFIXES, **cors_options):
        self.app = app
        self.prefixes = tuple(prefixes)
        self.cors = CORSMiddleware(app, **cors_options)

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["path"].startswith(self.prefixes):
            return await self.cors(scope, receive, send)
        return await self.app(scope, receive, send)
