from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.admin import create_api_key
from app.db import get_db
from app.errors import ApiError
from app.models import ApiKey
from app.schemas import ApiKeyCreatedOut, ApiKeyCreateIn, ApiKeyOut
from app.security import AuthContext, require_scope

router = APIRouter()


def _out(k: ApiKey) -> dict:
    return dict(id=k.id, name=k.name, scopes=list(k.scopes), key_prefix=k.key_prefix,
                active=k.active, created_at_ms=k.created_at_ms,
                last_used_at_ms=k.last_used_at_ms, revoked_at_ms=k.revoked_at_ms)


@router.post("/v1/api-keys", status_code=201, response_model=ApiKeyCreatedOut)
def create_key(body: ApiKeyCreateIn, request: Request,
               ctx: AuthContext = Depends(require_scope("keys:admin")),
               db: Session = Depends(get_db)):
    held = set(ctx.key.scopes or [])
    missing = [s for s in body.scopes if s not in held]
    if missing:  # a key may never hand out more power than it has itself
        raise ApiError(403, "forbidden_scope",
                       f"This API key cannot grant scopes it does not hold: {', '.join(missing)}.")
    active = db.scalar(select(func.count()).select_from(ApiKey).where(
        ApiKey.partner_id == ctx.partner.id, ApiKey.active.is_(True)))
    if active >= request.app.state.settings.max_api_keys_per_partner:
        raise ApiError(409, "api_key_limit_reached",
                       "The limit of active API keys has been reached. Revoke an unused key first.")
    key, raw = create_api_key(db, ctx.partner.id, body.name, body.scopes, request.app.state.clock())
    db.commit()
    return ApiKeyCreatedOut(**_out(key), key=raw)


@router.get("/v1/api-keys")
def list_keys(ctx: AuthContext = Depends(require_scope("keys:admin")),
              db: Session = Depends(get_db)):
    keys = db.scalars(select(ApiKey).where(ApiKey.partner_id == ctx.partner.id)
                      .order_by(ApiKey.created_at_ms, ApiKey.id))
    return {"data": [ApiKeyOut(**_out(k)).model_dump() for k in keys]}


@router.delete("/v1/api-keys/{key_id}", status_code=204)
def revoke_key(key_id: str, request: Request,
               ctx: AuthContext = Depends(require_scope("keys:admin")),
               db: Session = Depends(get_db)):
    key = db.get(ApiKey, key_id)
    if key is None or key.partner_id != ctx.partner.id:
        raise ApiError(404, "api_key_not_found", "API key not found")
    if key.active:  # revoking twice is harmless
        key.active = False
        key.revoked_at_ms = request.app.state.clock()
        db.commit()
    return Response(status_code=204)
