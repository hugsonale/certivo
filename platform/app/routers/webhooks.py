from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import and_, or_, select, update
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import ApiError
from app.models import (
    WebhookAttempt,
    WebhookDelivery,
    WebhookEndpoint,
    WebhookOutbox,
    new_id,
)
from app.paging import decode_cursor, encode_cursor
from app.schemas import (
    DeliveryStatus,
    WebhookAttemptOut,
    WebhookDeliveryOut,
    WebhookEndpointCreatedOut,
    WebhookEndpointCreateIn,
    WebhookEndpointOut,
    WebhookSecretRotatedOut,
)
from app.security import AuthContext, require_scope
from app.webhook_engine import OPEN_STATES
from app.webhook_events import TEST_EVENT
from app.webhook_sender import UrlNotAllowed, parse_target

router = APIRouter()
ATTEMPTS_SHOWN = 10


def _new_secret() -> str:
    return "whsec_" + secrets.token_urlsafe(32)


def _endpoint_out(e: WebhookEndpoint) -> dict:
    return dict(id=e.id, url=e.url, event_types=list(e.event_types), description=e.description,
                status=e.status, created_at_ms=e.created_at_ms)


def _own_endpoint(db: Session, ctx: AuthContext, endpoint_id: str) -> WebhookEndpoint:
    endpoint = db.get(WebhookEndpoint, endpoint_id)
    if endpoint is None or endpoint.partner_id != ctx.partner.id:
        raise ApiError(404, "webhook_endpoint_not_found", "Webhook endpoint not found")
    return endpoint


def _active_endpoint(db: Session, ctx: AuthContext, endpoint_id: str) -> WebhookEndpoint:
    endpoint = _own_endpoint(db, ctx, endpoint_id)
    if endpoint.status != "active":
        raise ApiError(404, "webhook_endpoint_not_found", "Webhook endpoint not found")
    return endpoint


@router.post("/v1/webhook-endpoints", status_code=201, response_model=WebhookEndpointCreatedOut)
def create_endpoint(body: WebhookEndpointCreateIn, request: Request,
                    ctx: AuthContext = Depends(require_scope("webhooks:write")),
                    db: Session = Depends(get_db)):
    settings = request.app.state.settings
    try:
        parse_target(body.url, allow_http=settings.env == "dev",
                     allow_private=settings.webhook_allow_private_targets)
    except UrlNotAllowed as exc:
        raise ApiError(422, "webhook_url_invalid", str(exc)) from exc
    active = len(list(db.scalars(select(WebhookEndpoint.id).where(
        WebhookEndpoint.partner_id == ctx.partner.id, WebhookEndpoint.status == "active"))))
    if active >= settings.webhook_max_endpoints_per_partner:
        raise ApiError(409, "webhook_endpoint_limit_reached",
                       "The limit of webhook endpoints has been reached. Delete an unused one first.")
    secret = _new_secret()
    endpoint = WebhookEndpoint(
        id=new_id("whe"), partner_id=ctx.partner.id, url=body.url, event_types=body.event_types,
        description=body.description, status="active",
        secret_encrypted=request.app.state.secretbox.encrypt(secret),
        created_at_ms=request.app.state.clock())
    db.add(endpoint)
    db.commit()
    return WebhookEndpointCreatedOut(**_endpoint_out(endpoint), secret=secret)


@router.get("/v1/webhook-endpoints")
def list_endpoints(ctx: AuthContext = Depends(require_scope("webhooks:read")),
                   db: Session = Depends(get_db)):
    rows = db.scalars(select(WebhookEndpoint).where(
        WebhookEndpoint.partner_id == ctx.partner.id, WebhookEndpoint.status == "active")
        .order_by(WebhookEndpoint.created_at_ms, WebhookEndpoint.id))
    return {"data": [WebhookEndpointOut(**_endpoint_out(e)).model_dump() for e in rows]}


@router.delete("/v1/webhook-endpoints/{endpoint_id}", status_code=204)
def delete_endpoint(endpoint_id: str, request: Request,
                    ctx: AuthContext = Depends(require_scope("webhooks:write")),
                    db: Session = Depends(get_db)):
    endpoint = _own_endpoint(db, ctx, endpoint_id)
    if endpoint.status == "active":  # deleting twice is harmless
        endpoint.status = "deleted"
        endpoint.deleted_at_ms = request.app.state.clock()
        # whatever was still waiting to be sent to it will now never be sent
        db.execute(update(WebhookDelivery).where(
            WebhookDelivery.endpoint_id == endpoint.id, WebhookDelivery.status.in_(OPEN_STATES))
            .values(status="dead", last_error="endpoint_deleted", locked_until_ms=None,
                    claim_token=None))
        db.commit()
    return Response(status_code=204)


@router.post("/v1/webhook-endpoints/{endpoint_id}/rotate-secret",
             response_model=WebhookSecretRotatedOut)
def rotate_secret(endpoint_id: str, request: Request,
                  ctx: AuthContext = Depends(require_scope("webhooks:write")),
                  db: Session = Depends(get_db)):
    """New secret now. The old one keeps signing alongside it for a while, so the partner can switch
    over without dropping messages (the signature header then carries two v1 values)."""
    endpoint = _active_endpoint(db, ctx, endpoint_id)
    settings, box = request.app.state.settings, request.app.state.secretbox
    now = request.app.state.clock()
    secret = _new_secret()
    endpoint.previous_secret_encrypted = endpoint.secret_encrypted
    endpoint.previous_secret_expires_at_ms = now + settings.webhook_secret_overlap_s * 1000
    endpoint.secret_encrypted = box.encrypt(secret)
    db.commit()
    return WebhookSecretRotatedOut(
        id=endpoint.id, secret=secret,
        previous_secret_valid_until_ms=endpoint.previous_secret_expires_at_ms)


@router.post("/v1/webhook-endpoints/{endpoint_id}/test", status_code=202)
def send_test_event(endpoint_id: str, request: Request,
                    ctx: AuthContext = Depends(require_scope("webhooks:write")),
                    db: Session = Depends(get_db)):
    endpoint = _active_endpoint(db, ctx, endpoint_id)
    event = WebhookOutbox(event_id=new_id("evt"), partner_id=ctx.partner.id, event_type=TEST_EVENT,
                          payload={}, created_at_ms=request.app.state.clock(),
                          target_endpoint_id=endpoint.id)
    db.add(event)
    db.commit()
    return {"event_id": event.event_id}


def _delivery_out(delivery: WebhookDelivery, event_id: str, event_type: str,
                  attempts: list[WebhookAttempt]) -> WebhookDeliveryOut:
    return WebhookDeliveryOut(
        id=delivery.id, event_id=event_id, event_type=event_type, endpoint_id=delivery.endpoint_id,
        status=delivery.status, attempt_count=delivery.attempt_count,
        next_attempt_at_ms=delivery.next_attempt_at_ms if delivery.status in OPEN_STATES else None,
        last_status_code=delivery.last_status_code, last_error=delivery.last_error,
        created_at_ms=delivery.created_at_ms, delivered_at_ms=delivery.delivered_at_ms,
        attempts=[WebhookAttemptOut(attempted_at_ms=a.attempted_at_ms, status_code=a.status_code,
                                    error=a.error, duration_ms=a.duration_ms) for a in attempts])


def _recent_attempts(db: Session, delivery_ids: list[str]) -> dict[str, list[WebhookAttempt]]:
    grouped: dict[str, list[WebhookAttempt]] = {d: [] for d in delivery_ids}
    if delivery_ids:
        for attempt in db.scalars(select(WebhookAttempt).where(
                WebhookAttempt.delivery_id.in_(delivery_ids)).order_by(WebhookAttempt.id.desc())):
            if len(grouped[attempt.delivery_id]) < ATTEMPTS_SHOWN:
                grouped[attempt.delivery_id].append(attempt)
    return grouped


@router.get("/v1/webhook-deliveries")
def list_deliveries(ctx: AuthContext = Depends(require_scope("webhooks:read")),
                    db: Session = Depends(get_db),
                    endpoint_id: str | None = None, status: DeliveryStatus | None = None,
                    limit: int = Query(25, ge=1, le=100), cursor: str | None = None):
    """The delivery log, newest first. Page with `cursor` (use `next_cursor` from the previous page)."""
    query = (select(WebhookDelivery, WebhookOutbox.event_id, WebhookOutbox.event_type)
             .join(WebhookOutbox, WebhookOutbox.id == WebhookDelivery.outbox_id)
             .where(WebhookDelivery.partner_id == ctx.partner.id))
    if endpoint_id:
        query = query.where(WebhookDelivery.endpoint_id == endpoint_id)
    if status:
        query = query.where(WebhookDelivery.status == status)
    if cursor:
        created, last_id = decode_cursor(cursor)
        query = query.where(or_(WebhookDelivery.created_at_ms < created,
                                and_(WebhookDelivery.created_at_ms == created,
                                     WebhookDelivery.id < last_id)))
    rows = db.execute(query.order_by(WebhookDelivery.created_at_ms.desc(), WebhookDelivery.id.desc())
                      .limit(limit + 1)).all()
    page, more = rows[:limit], len(rows) > limit
    attempts = _recent_attempts(db, [r[0].id for r in page])
    body: dict = {"data": [_delivery_out(d, eid, etype, attempts[d.id]).model_dump()
                           for d, eid, etype in page]}
    if more:
        last = page[-1][0]
        body["next_cursor"] = encode_cursor(last.created_at_ms, last.id)
    return body


@router.post("/v1/webhook-deliveries/{delivery_id}/retry", status_code=202,
             response_model=WebhookDeliveryOut)
def retry_delivery(delivery_id: str, request: Request,
                   ctx: AuthContext = Depends(require_scope("webhooks:write")),
                   db: Session = Depends(get_db)):
    """Send a failed or dead delivery again: it goes back to the front of the queue with a fresh
    set of attempts."""
    delivery = db.get(WebhookDelivery, delivery_id)
    if delivery is None or delivery.partner_id != ctx.partner.id:
        raise ApiError(404, "webhook_delivery_not_found", "Webhook delivery not found")
    if delivery.status not in ("dead", "retrying"):
        raise ApiError(409, "delivery_not_retryable",
                       f"A delivery that is {delivery.status} cannot be retried.")
    endpoint = db.get(WebhookEndpoint, delivery.endpoint_id)
    if endpoint is None or endpoint.status != "active":
        raise ApiError(409, "delivery_not_retryable", "Its webhook endpoint has been deleted.")
    delivery.status = "pending"
    delivery.failures_in_round = 0
    delivery.next_attempt_at_ms = request.app.state.clock()
    delivery.locked_until_ms = None
    delivery.claim_token = None
    db.commit()
    event = db.get(WebhookOutbox, delivery.outbox_id)
    return _delivery_out(delivery, event.event_id, event.event_type,
                         _recent_attempts(db, [delivery.id])[delivery.id])
