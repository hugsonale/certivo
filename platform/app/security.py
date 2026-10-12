from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass

from fastapi import Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import ApiError
from app.models import ApiKey, ContinuousSession, Partner
from app.ratelimit import Decision, RateLimiter
from app.scopes import Scope

LAST_USED_RESOLUTION_MS = 60_000  # `last_used_at_ms` is written at most once a minute per key


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def new_api_key() -> str:
    return "cvk_" + secrets.token_urlsafe(32)


def new_sdk_token() -> str:
    return "skt_" + secrets.token_urlsafe(32)


def _bearer(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    return token.strip() if scheme.lower() == "bearer" and token.strip() else None


def client_ip(request: Request) -> str:
    """The caller's network address. Only trust X-Forwarded-For when we know how many reverse
    proxies sit in front of us; otherwise anyone could dodge limits by sending the header."""
    hops = request.app.state.settings.trusted_proxy_hops
    if hops > 0:
        parts = [p.strip() for p in request.headers.get("x-forwarded-for", "").split(",")
                 if p.strip()]
        if len(parts) >= hops:
            return parts[-hops]
    return request.client.host if request.client else "unknown"


def _limiter(request: Request) -> RateLimiter:
    return request.app.state.limiter


def _rate_limited(decision: Decision) -> ApiError:
    return ApiError(
        429, "rate_limited",
        f"Too many requests. Try again in {decision.retry_after_s} seconds.",
        headers={"Retry-After": str(decision.retry_after_s),
                 "RateLimit-Limit": str(decision.limit),
                 "RateLimit-Remaining": "0",
                 "RateLimit-Reset": str(decision.reset_s)},
    )


def _set_rate_headers(response: Response, decision: Decision) -> None:
    response.headers["RateLimit-Limit"] = str(decision.limit)
    response.headers["RateLimit-Remaining"] = str(decision.remaining)
    response.headers["RateLimit-Reset"] = str(decision.reset_s)


def _failure_keys(request: Request, presented: str | None) -> list[str]:
    keys = [f"authfail:ip:{client_ip(request)}"]
    if presented:
        keys.append(f"authfail:prefix:{presented[:12]}")
    return keys


def _refuse_if_too_many_failures(request: Request, presented: str | None) -> None:
    limit = request.app.state.settings.rate_limit_auth_failures_per_minute
    for key in _failure_keys(request, presented):
        decision = _limiter(request).check(key, limit, consume=False)
        if not decision.allowed:
            raise _rate_limited(decision)


def _record_failure(request: Request, presented: str | None) -> None:
    limit = request.app.state.settings.rate_limit_auth_failures_per_minute
    for key in _failure_keys(request, presented):
        _limiter(request).check(key, limit)


@dataclass
class AuthContext:
    partner: Partner
    key: ApiKey


def require_scope(scope: Scope):
    """Dependency: a valid, unrevoked API key that holds `scope` and is within its rate limit."""

    def dependency(request: Request, response: Response,
                   db: Session = Depends(get_db)) -> AuthContext:
        settings = request.app.state.settings
        token = _bearer(request)
        _refuse_if_too_many_failures(request, token)
        if not token:
            _record_failure(request, None)
            raise ApiError(401, "missing_api_key", "Authorization: Bearer <api key> is required")
        key = db.scalar(select(ApiKey).where(ApiKey.key_hash == sha256_hex(token),
                                             ApiKey.active.is_(True)))
        partner = db.get(Partner, key.partner_id) if key else None
        if key is None or partner is None:
            _record_failure(request, token)
            raise ApiError(401, "invalid_api_key", "API key is not valid")

        decision = _limiter(request).check(f"key:{key.id}", settings.rate_limit_key_per_minute)
        if not decision.allowed:
            raise _rate_limited(decision)
        _set_rate_headers(response, decision)

        if scope not in (key.scopes or []):
            raise ApiError(403, "forbidden_scope", f"This API key does not have the '{scope}' scope.")

        now = request.app.state.clock()
        if key.last_used_at_ms is None or now - key.last_used_at_ms >= LAST_USED_RESOLUTION_MS:
            key.last_used_at_ms = now
            db.commit()
        return AuthContext(partner=partner, key=key)

    return dependency


def require_sdk_session(session_id: str, request: Request, response: Response,
                        db: Session = Depends(get_db)) -> ContinuousSession:
    """Dependency: a valid, unexpired SDK token for exactly this session, within its rate limit."""
    settings = request.app.state.settings
    token = _bearer(request)
    _refuse_if_too_many_failures(request, token)
    if not token:
        _record_failure(request, None)
        raise ApiError(401, "missing_session_token", "Session token is required")
    session = db.get(ContinuousSession, session_id)
    if session is None:
        _record_failure(request, token)
        raise ApiError(404, "session_not_found", "Session not found")
    if not hmac.compare_digest(session.sdk_token_hash, sha256_hex(token)):
        _record_failure(request, token)
        raise ApiError(401, "invalid_session_token", "Session token is not valid for this session")
    if request.app.state.clock() >= session.sdk_token_expires_at_ms:
        raise ApiError(401, "session_token_expired", "Session token has expired")

    decision = _limiter(request).check(f"session:{session.id}",
                                       settings.rate_limit_session_per_minute)
    if not decision.allowed:
        raise _rate_limited(decision)
    _set_rate_headers(response, decision)
    return session
