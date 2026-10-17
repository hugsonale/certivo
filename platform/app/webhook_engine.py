"""The webhook delivery state machine (docs/spec/base/05-webhooks.md).

The DATABASE is the source of truth for what is pending and when it is next due. The Celery worker
only decides WHEN to run the steps below, so losing Redis never loses an event: it just delays it.

    event written in the same transaction as the change that caused it   (app/services/sessions.py)
        -> fan_out():    one delivery per subscribed endpoint
        -> claim_due():  lock the deliveries that are due, hand each a one-time claim token
        -> attempt():    sign, send, record the try, then mark delivered / retrying / dead

Delivery is AT LEAST ONCE: if a worker dies after the partner answered but before we recorded it, the
delivery is sent again. Receivers must de-duplicate by event ID (app/webhook_verify.ReplayGuard).
"""
from __future__ import annotations

import json
import logging
import secrets
from collections.abc import Callable

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.models import (
    WebhookAttempt,
    WebhookDelivery,
    WebhookEndpoint,
    WebhookOutbox,
    new_id,
)
from app.secretbox import SecretBox
from app.webhook_events import API_VERSION
from app.webhook_sender import HttpSender, SendResult
from app.webhook_verify import build_signature_header

log = logging.getLogger("certivo.webhooks")
OPEN_STATES = ("pending", "retrying")
Sender = Callable[..., SendResult]


def envelope_bytes(event: WebhookOutbox) -> bytes:
    """The exact bytes sent as the request body (and signed). Plain ASCII JSON, keys sorted."""
    envelope = {
        "id": event.event_id,
        "type": event.event_type,
        "created_at_ms": event.created_at_ms,
        "api_version": API_VERSION,
        "partner_id": event.partner_id,
        "data": event.payload,
    }
    return json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode()


class WebhookEngine:
    def __init__(self, settings: Settings, session_factory: sessionmaker[Session],
                 clock: Callable[[], int], secretbox: SecretBox, sender: Sender | None = None):
        self.settings = settings
        self._sessions = session_factory
        self._clock = clock
        self._box = secretbox
        self._sender = sender or HttpSender()

    # ---------------------------------------------------------------- 1. events -> deliveries

    def fan_out(self, limit: int = 500) -> int:
        """Turn new events into deliveries. Returns how many deliveries were created."""
        with self._sessions() as db:
            event_ids = list(db.scalars(
                select(WebhookOutbox.id).where(WebhookOutbox.fanned_out_at_ms.is_(None))
                .order_by(WebhookOutbox.id).limit(limit)))
        return sum(self._fan_out_one(event_id) for event_id in event_ids)

    def _fan_out_one(self, outbox_id: int) -> int:
        now = self._clock()
        with self._sessions() as db:  # one transaction per event: one bad event cannot block the rest
            event = db.get(WebhookOutbox, outbox_id)
            if event is None or event.fanned_out_at_ms is not None:
                return 0
            if event.target_endpoint_id:  # a "send test" event goes to exactly one endpoint
                endpoint = db.get(WebhookEndpoint, event.target_endpoint_id)
                endpoints = [endpoint] if endpoint and endpoint.status == "active" else []
            else:
                endpoints = [
                    e for e in db.scalars(select(WebhookEndpoint).where(
                        WebhookEndpoint.partner_id == event.partner_id,
                        WebhookEndpoint.status == "active"))
                    if "*" in e.event_types or event.event_type in e.event_types
                ]
            for endpoint in endpoints:
                db.add(WebhookDelivery(
                    id=new_id("dlv"), outbox_id=event.id, endpoint_id=endpoint.id,
                    partner_id=event.partner_id, status="pending", attempt_count=0,
                    failures_in_round=0, next_attempt_at_ms=now, created_at_ms=now))
            event.fanned_out_at_ms = now
            try:
                db.commit()
            except IntegrityError:  # another worker fanned this event out first
                db.rollback()
                return 0
            return len(endpoints)

    # ---------------------------------------------------------------- 2. claiming

    def claim_due(self, limit: int | None = None) -> list[tuple[str, str]]:
        """Lock deliveries that are due. Returns [(delivery_id, claim_token)].

        The lock is an atomic UPDATE, so two workers can never claim the same delivery. If a worker
        dies, the lock simply runs out (webhook_lease_s) and the delivery becomes claimable again.
        """
        limit = limit or self.settings.webhook_batch_size
        now = self._clock()
        lease_until = now + self.settings.webhook_lease_s * 1000
        claimed: list[tuple[str, str]] = []
        with self._sessions() as db:
            due = list(db.scalars(
                select(WebhookDelivery.id).where(
                    WebhookDelivery.status.in_(OPEN_STATES),
                    WebhookDelivery.next_attempt_at_ms <= now,
                    or_(WebhookDelivery.locked_until_ms.is_(None),
                        WebhookDelivery.locked_until_ms < now))
                .order_by(WebhookDelivery.next_attempt_at_ms).limit(limit)))
            for delivery_id in due:
                token = secrets.token_hex(16)
                result = db.execute(
                    update(WebhookDelivery).where(
                        WebhookDelivery.id == delivery_id,
                        WebhookDelivery.status.in_(OPEN_STATES),
                        WebhookDelivery.next_attempt_at_ms <= now,
                        or_(WebhookDelivery.locked_until_ms.is_(None),
                            WebhookDelivery.locked_until_ms < now))
                    .values(locked_until_ms=lease_until, claim_token=token))
                if result.rowcount == 1:
                    claimed.append((delivery_id, token))
            db.commit()
        return claimed

    # ---------------------------------------------------------------- 3. one attempt

    def attempt(self, delivery_id: str, claim_token: str) -> str:
        """Try one delivery. Returns delivered, retrying, dead, or skipped (nothing was sent)."""
        started = self._clock()
        with self._sessions() as db:
            delivery = db.get(WebhookDelivery, delivery_id)
            if (delivery is None or delivery.status not in OPEN_STATES
                    or delivery.claim_token != claim_token):
                return "skipped"  # finished, reset by a manual retry, or claimed by someone else
            endpoint = db.get(WebhookEndpoint, delivery.endpoint_id)
            event = db.get(WebhookOutbox, delivery.outbox_id)
            if endpoint is None or endpoint.status != "active" or event is None:
                self._finish(db, delivery, started, SendResult(None, "endpoint_deleted", 0),
                             log_attempt=False, force_dead=True)
                db.commit()
                return "dead"
            secrets_in_use = [self._box.decrypt(endpoint.secret_encrypted)]
            if (endpoint.previous_secret_encrypted and endpoint.previous_secret_expires_at_ms
                    and started < endpoint.previous_secret_expires_at_ms):
                secrets_in_use.append(self._box.decrypt(endpoint.previous_secret_encrypted))
            body = envelope_bytes(event)
            headers = {
                "Content-Type": "application/json",
                "User-Agent": "Certivo-Webhooks/1",
                "Certivo-Event-Id": event.event_id,
                "Certivo-Event-Type": event.event_type,
                # signed fresh for every attempt, so the replay window always applies to this try
                "Certivo-Signature": build_signature_header(secrets_in_use, started, body),
            }
            url = endpoint.url
        # The database connection is released above: nothing is held open during the network call.
        result = self._sender(
            url, body, headers, timeout_s=self.settings.webhook_timeout_s,
            allow_private=self.settings.webhook_allow_private_targets,
            allow_http=self.settings.env == "dev")
        with self._sessions() as db:
            delivery = db.get(WebhookDelivery, delivery_id)
            outcome = self._finish(db, delivery, started, result)
            db.commit()
            return outcome

    def _finish(self, db: Session, delivery: WebhookDelivery, started: int, result: SendResult,
                *, log_attempt: bool = True, force_dead: bool = False) -> str:
        now = self._clock()
        if log_attempt:
            db.add(WebhookAttempt(delivery_id=delivery.id, attempted_at_ms=started,
                                  status_code=result.status_code, error=result.error,
                                  duration_ms=result.duration_ms))
        delivery.locked_until_ms = None
        delivery.claim_token = None
        if delivery.status not in OPEN_STATES:
            # Something settled it while we were sending (for example the endpoint was deleted).
            # The attempt is logged above, but the settled state must not be rewritten.
            return delivery.status
        delivery.last_status_code = result.status_code
        delivery.last_error = result.error
        if log_attempt:
            delivery.attempt_count += 1
        if result.error is None:
            delivery.status, delivery.delivered_at_ms = "delivered", now
            return "delivered"
        delivery.failures_in_round += 1
        delays = self.settings.retry_delays_s
        if force_dead or delivery.failures_in_round > len(delays):
            delivery.status = "dead"  # every attempt in this round failed: needs a manual retry
            return "dead"
        delivery.status = "retrying"
        delivery.next_attempt_at_ms = now + delays[delivery.failures_in_round - 1] * 1000
        return "retrying"

    # ---------------------------------------------------------------- convenience

    def run_once(self) -> dict[str, int]:
        """Do one full pass in this process: fan out, claim, attempt. Used by tests, by the simple
        development loop (scripts/run_webhook_loop.py) and as the reference for the Celery tasks."""
        counts = {"fanned_out": self.fan_out(), "delivered": 0, "retrying": 0, "dead": 0, "skipped": 0}
        for delivery_id, token in self.claim_due():
            counts[self.attempt(delivery_id, token)] += 1
        return counts
