from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import ApiError
from app.models import Policy
from app.paging import decode_cursor, encode_cursor
from app.schemas import PolicyCreateIn, PolicyOut
from app.security import AuthContext, require_scope
from app.services import policies as svc

router = APIRouter()


@router.post("/v1/policies", status_code=201, response_model=PolicyOut)
def create_policy(body: PolicyCreateIn, request: Request,
                  ctx: AuthContext = Depends(require_scope("policies:write")),
                  db: Session = Depends(get_db)):
    """Create the next version of this partner's policy for a use case. Old versions never change."""
    policy = svc.create_policy(db, ctx.partner, body.use_case, body.settings, request.app.state.clock())
    return svc.policy_out(policy)


def _visible(partner_id: str):
    return or_(Policy.partner_id == partner_id, Policy.partner_id.is_(None))


@router.get("/v1/policies")
def list_policies(use_case: str | None = Query(None, pattern=r"^[a-z0-9_]{1,64}$"),
                  limit: int = Query(25, ge=1, le=100), cursor: str | None = None,
                  ctx: AuthContext = Depends(require_scope("policies:read")),
                  db: Session = Depends(get_db)):
    """Your policies, newest first, and Certivo's built-in defaults (which you cannot change)."""
    query = select(Policy).where(_visible(ctx.partner.id))
    if use_case:
        query = query.where(Policy.use_case == use_case)
    if cursor:
        created, last_id = decode_cursor(cursor)
        query = query.where(or_(Policy.created_at_ms < created,
                                and_(Policy.created_at_ms == created, Policy.id < last_id)))
    rows = list(db.scalars(query.order_by(Policy.created_at_ms.desc(), Policy.id.desc()).limit(limit + 1)))
    page, more = rows[:limit], len(rows) > limit
    body: dict = {"data": [svc.policy_out(p).model_dump() for p in page]}
    if more:
        body["next_cursor"] = encode_cursor(page[-1].created_at_ms, page[-1].id)
    return body


@router.get("/v1/policies/{policy_id}", response_model=PolicyOut)
def get_policy(policy_id: str, ctx: AuthContext = Depends(require_scope("policies:read")),
               db: Session = Depends(get_db)):
    policy = db.scalar(select(Policy).where(Policy.id == policy_id, _visible(ctx.partner.id)))
    if policy is None:
        raise ApiError(404, "policy_not_found", "Policy not found")
    return svc.policy_out(policy)
