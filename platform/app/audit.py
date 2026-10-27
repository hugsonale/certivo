"""The audit log (P0-13, Doc 9 section 8, docs/adr/0019).

WHAT IT RECORDS: every change to a partner, an API key, a policy, a webhook endpoint (including its
signing secret) and the platform's attestation signing keys. Who did it (the API key, or "system" for
startup and scripts), when, which request (the ID in the logs), and what changed.

HOW: a listener on the database session looks at everything about to be written. For a change to one of
the tracked tables it adds an AuditEvent row to the SAME write. So:
  * no code path, present or future, can change a tracked table without leaving a record, and
  * the record and the change commit or roll back together.

WHAT IT NEVER RECORDS: secrets, key hashes, encrypted secrets, webhook URL paths or query strings
(they can hold tokens; only the host is kept), or anything about a person.

APPEND-ONLY: this module refuses to update or delete an AuditEvent through the ORM, and migration 0008
makes the database refuse UPDATE, DELETE and TRUNCATE on the table. A database administrator can still
remove those protections; the real defence against that is a database role that cannot, and shipping
the log elsewhere. Both are listed in docs/adr/0019 as decisions for the production environment (P1-17).

NOT AUDITED, on purpose: device registrations and SDK session tokens. They happen once per end-user
device or call, so they are operational data rather than administrative changes. Revisit with the
Trusted Device Layer (P1-02).
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import event
from sqlalchemy.orm import Session, attributes

from app.models import (
    ApiKey,
    AttestationKey,
    AuditEvent,
    Partner,
    Policy,
    WebhookEndpoint,
)
from app.timeutil import now_ms

log = logging.getLogger("certivo.audit")

INFO_ACTOR = "audit_actor"        # session.info key: (actor_type, actor_id)
INFO_REQUEST_ID = "request_id"    # session.info key
INFO_CLOCK = "clock"              # session.info key: callable returning epoch milliseconds
_QUEUE = "_audit_log_queue"

# The complete list of actions that can appear. Tests check this list, and the docs repeat it.
ACTIONS = (
    "partner.created",
    "api_key.created", "api_key.revoked",
    "policy.created",
    "webhook_endpoint.created", "webhook_endpoint.updated",
    "webhook_endpoint.secret_rotated", "webhook_endpoint.deleted",
    "signing_key.registered", "signing_key.retired",
)


class AuditImmutableError(RuntimeError):
    """Something tried to change or delete an audit record."""


def set_context(db: Session, *, request_id: str | None = None,
                clock: Callable[[], int] | None = None) -> None:
    """Called when a database session is opened for a request."""
    if request_id:
        db.info[INFO_REQUEST_ID] = request_id
    if clock:
        db.info[INFO_CLOCK] = clock


def set_actor(db: Session, actor_type: str, actor_id: str | None) -> None:
    """Say who is making the changes in this session. Without this the actor is 'system'."""
    db.info[INFO_ACTOR] = (actor_type, actor_id)


def _changed(obj: Any, name: str) -> bool:
    return attributes.get_history(obj, name).has_changes()


def _host(url: str | None) -> str | None:
    """Only the host of a webhook URL: a path or query string can carry a secret token."""
    try:
        return urlsplit(url or "").hostname
    except ValueError:
        return None


def _describe_new(obj: Any) -> list[tuple[str, str, str | None, str | None, dict]]:
    """(action, target_type, target_id, partner_id, details) for a row being inserted."""
    if isinstance(obj, Partner):
        return [("partner.created", "partner", obj.id, obj.id, {"name": obj.name})]
    if isinstance(obj, ApiKey):
        return [("api_key.created", "api_key", obj.id, obj.partner_id,
                 {"name": obj.name, "scopes": list(obj.scopes or [])})]
    if isinstance(obj, Policy):
        return [("policy.created", "policy", obj.id, obj.partner_id,
                 {"use_case": obj.use_case, "version": obj.version, "config": obj.config})]
    if isinstance(obj, WebhookEndpoint):
        return [("webhook_endpoint.created", "webhook_endpoint", obj.id, obj.partner_id,
                 {"host": _host(obj.url), "event_types": list(obj.event_types or [])})]
    if isinstance(obj, AttestationKey):
        return [("signing_key.registered", "signing_key", obj.key_id, None,
                 {"alg": obj.alg, "status": obj.status})]
    return []


def _describe_update(obj: Any) -> list[tuple[str, str, str | None, str | None, dict]]:
    """The same, for a row being changed. Only the changes that matter; bookkeeping such as
    `last_used_at_ms` is ignored."""
    out: list[tuple[str, str, str | None, str | None, dict]] = []
    if isinstance(obj, ApiKey):
        if _changed(obj, "active") and not obj.active:
            out.append(("api_key.revoked", "api_key", obj.id, obj.partner_id, {"name": obj.name}))
    elif isinstance(obj, WebhookEndpoint):
        if _changed(obj, "status") and obj.status == "deleted":
            out.append(("webhook_endpoint.deleted", "webhook_endpoint", obj.id, obj.partner_id,
                        {"host": _host(obj.url)}))
        if _changed(obj, "secret_encrypted"):  # the fact of rotation, never any secret material
            out.append(("webhook_endpoint.secret_rotated", "webhook_endpoint", obj.id, obj.partner_id, {}))
        edited = [name for name in ("url", "event_types", "description") if _changed(obj, name)]
        if edited:
            out.append(("webhook_endpoint.updated", "webhook_endpoint", obj.id, obj.partner_id,
                        {"changed": edited, "host": _host(obj.url)}))
    elif isinstance(obj, AttestationKey):
        if _changed(obj, "status") and obj.status == "retired":
            out.append(("signing_key.retired", "signing_key", obj.key_id, None, {"alg": obj.alg}))
    return out


_TRACKED = (Partner, ApiKey, Policy, WebhookEndpoint, AttestationKey)


@event.listens_for(Session, "before_flush")
def _record_audit_events(session: Session, flush_context, instances) -> None:
    for obj in list(session.dirty) + list(session.deleted):
        if isinstance(obj, AuditEvent):
            raise AuditImmutableError("audit records are append-only: they can never be changed or deleted")

    rows: list[tuple[str, str, str | None, str | None, dict]] = []
    for obj in list(session.new):
        rows.extend(_describe_new(obj))
    for obj in list(session.dirty):
        if session.is_modified(obj, include_collections=False):
            rows.extend(_describe_update(obj))
    for obj in list(session.deleted):
        if isinstance(obj, _TRACKED):  # the application never does this; if it ever does, it is recorded
            rows.append((f"{type(obj).__name__.lower()}.row_deleted", type(obj).__name__.lower(),
                         getattr(obj, "id", None) or getattr(obj, "key_id", None), None, {}))
    if not rows:
        return

    actor_type, actor_id = session.info.get(INFO_ACTOR, ("system", None))
    request_id = session.info.get(INFO_REQUEST_ID)
    at_ms = (session.info.get(INFO_CLOCK) or now_ms)()
    queue = session.info.setdefault(_QUEUE, [])
    for action, target_type, target_id, partner_id, details in rows:
        session.add(AuditEvent(at_ms=at_ms, action=action, partner_id=partner_id, actor_type=actor_type,
                               actor_id=actor_id, request_id=request_id, target_type=target_type,
                               target_id=target_id, details=details))
        queue.append((action, target_type, target_id, partner_id, actor_type, actor_id))


@event.listens_for(Session, "after_commit")
def _log_committed(session: Session) -> None:
    """Only once the change is really saved do we write the matching log line."""
    for action, target_type, target_id, partner_id, actor_type, actor_id in session.info.pop(_QUEUE, []):
        log.info("audit", extra={"action": action, "target_type": target_type, "target_id": target_id,
                                 "partner_id": partner_id, "actor_type": actor_type, "actor_id": actor_id,
                                 "request_id": session.info.get(INFO_REQUEST_ID)})


@event.listens_for(Session, "after_rollback")
def _forget_rolled_back(session: Session) -> None:
    session.info.pop(_QUEUE, None)
