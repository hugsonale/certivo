from __future__ import annotations

import hashlib
import hmac
import secrets

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import ApiError
from app.models import ApiKey, ContinuousSession, Partner


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


def require_partner(request: Request, db: Session = Depends(get_db)) -> Partner:
    token = _bearer(request)
    if not token:
        raise ApiError(401, "missing_api_key", "Authorization: Bearer <api key> is required")
    key = db.scalar(select(ApiKey).where(ApiKey.key_hash == sha256_hex(token),
                                         ApiKey.active.is_(True)))
    partner = db.get(Partner, key.partner_id) if key else None
    if partner is None:
        raise ApiError(401, "invalid_api_key", "API key is not valid")
    return partner


def require_sdk_session(session_id: str, request: Request,
                        db: Session = Depends(get_db)) -> ContinuousSession:
    token = _bearer(request)
    if not token:
        raise ApiError(401, "missing_session_token", "Session token is required")
    session = db.get(ContinuousSession, session_id)
    if session is None:
        raise ApiError(404, "session_not_found", "Session not found")
    if not hmac.compare_digest(session.sdk_token_hash, sha256_hex(token)):
        raise ApiError(401, "invalid_session_token", "Session token is not valid for this session")
    return session
