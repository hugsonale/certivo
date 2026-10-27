"""The audit log (P0-13): every key, policy and credential change is recorded, in the same
transaction, and the record can never be changed or deleted. Uses the real migrations."""
import json

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app import audit
from app.audit import ACTIONS, AuditImmutableError
from app.db import make_engine, make_session_factory, upgrade_to_head
from app.models import (
    ApiKey,
    AttestationKey,
    AuditEvent,
    Partner,
    Policy,
    WebhookEndpoint,
    new_id,
)
from tests.obs_support import capture_logs

NOW = 1_760_000_000_000


@pytest.fixture
def factory(db_url):
    upgrade_to_head(db_url)  # idempotent; the tests below tag everything with IDs only they create
    engine = make_engine(db_url)
    yield make_session_factory(engine)
    engine.dispose()


@pytest.fixture
def partner_id(factory):
    pid = new_id("ptn")
    with factory() as db:
        db.add(Partner(id=pid, name="Audit Test Partner", created_at_ms=NOW))
        db.commit()
    return pid


def events(db, **where):
    stmt = select(AuditEvent).order_by(AuditEvent.id)
    for column, value in where.items():
        stmt = stmt.where(getattr(AuditEvent, column) == value)
    return list(db.scalars(stmt))


def new_key(pid, **overrides):
    fields = dict(id=new_id("key"), partner_id=pid, name="server key", key_hash=new_id("hash"),
                  key_prefix="cvk_abcdefgh", scopes=["sessions:read"], active=True, created_at_ms=NOW)
    return ApiKey(**{**fields, **overrides})


def test_creating_a_partner_and_a_key_is_recorded(factory):
    pid = new_id("ptn")
    with factory() as db:
        db.add(Partner(id=pid, name="Acme", created_at_ms=NOW))
        db.flush()  # the partner must exist before its key does (Postgres enforces the foreign key)
        key = new_key(pid, scopes=["sessions:read", "keys:admin"])
        db.add(key)
        db.commit()
        by_action = {e.action: e for e in events(db, partner_id=pid)}
    assert set(by_action) == {"partner.created", "api_key.created"}
    created = by_action["api_key.created"]
    assert created.target_type == "api_key" and created.target_id == key.id
    assert created.details == {"name": "server key", "scopes": ["sessions:read", "keys:admin"]}
    assert created.actor_type == "system" and created.actor_id is None


def test_no_secret_material_is_ever_stored_in_an_audit_record(factory, partner_id):
    secret_hash, prefix = new_id("hash"), "cvk_PREFIX99"
    with factory() as db:
        db.add(new_key(partner_id, key_hash=secret_hash, key_prefix=prefix))
        db.commit()
        stored = json.dumps([(e.details, e.target_id, e.actor_id) for e in events(db, partner_id=partner_id)])
    assert secret_hash not in stored and prefix not in stored


def test_who_when_and_which_request_are_recorded(factory, partner_id):
    with factory() as db:
        audit.set_actor(db, "api_key", "key_admin")
        audit.set_context(db, request_id="req_0123456789abcdef", clock=lambda: NOW + 5)
        db.add(new_key(partner_id))
        db.commit()
        (event,) = [e for e in events(db, partner_id=partner_id) if e.action == "api_key.created"]
    assert (event.actor_type, event.actor_id) == ("api_key", "key_admin")
    assert event.request_id == "req_0123456789abcdef"
    assert event.at_ms == NOW + 5


def test_revoking_a_key_is_recorded_but_routine_use_is_not(factory, partner_id):
    with factory() as db:
        key = new_key(partner_id)
        db.add(key)
        db.commit()
        before = len(events(db, partner_id=partner_id))

        key.last_used_at_ms = NOW + 1  # bookkeeping on every authenticated request: not an event
        db.commit()
        assert len(events(db, partner_id=partner_id)) == before

        key.active, key.revoked_at_ms = False, NOW + 2
        db.commit()
        revoked = events(db, partner_id=partner_id)[before:]
    assert [e.action for e in revoked] == ["api_key.revoked"]
    assert revoked[0].target_id == key.id


def test_a_new_policy_version_is_recorded_with_its_settings(factory, partner_id):
    config = {"thresholds": {"accept_milli": 700}, "re_evaluation_interval_ms": 5000}
    with factory() as db:
        policy = Policy(id=new_id("pol"), partner_id=partner_id, use_case=f"uc_{new_id('x')[:12]}",
                        version=1, config=config, created_at_ms=NOW)
        db.add(policy)
        db.commit()
        (event,) = [e for e in events(db, partner_id=partner_id) if e.action == "policy.created"]
    assert event.target_id == policy.id
    assert event.details == {"use_case": policy.use_case, "version": 1, "config": config}


def test_webhook_endpoint_changes_are_recorded_without_secrets_or_url_paths(factory, partner_id):
    with factory() as db:
        endpoint = WebhookEndpoint(
            id=new_id("whe"), partner_id=partner_id,
            url="https://hooks.example.com/in/PATHTOKEN?k=QUERYTOKEN", event_types=["*"],
            status="active", secret_encrypted="ENCRYPTED-SECRET-1", created_at_ms=NOW)
        db.add(endpoint)
        db.commit()

        endpoint.secret_encrypted = "ENCRYPTED-SECRET-2"   # a rotation
        db.commit()
        endpoint.event_types = ["session.paused"]           # an edit
        db.commit()
        endpoint.status, endpoint.deleted_at_ms = "deleted", NOW + 9
        db.commit()
        rows = [e for e in events(db, partner_id=partner_id) if e.target_id == endpoint.id]
    assert [e.action for e in rows] == [
        "webhook_endpoint.created", "webhook_endpoint.secret_rotated",
        "webhook_endpoint.updated", "webhook_endpoint.deleted"]
    assert rows[0].details == {"host": "hooks.example.com", "event_types": ["*"]}
    assert rows[1].details == {}
    assert rows[2].details == {"changed": ["event_types"], "host": "hooks.example.com"}
    stored = json.dumps([e.details for e in rows])
    for secret in ("PATHTOKEN", "QUERYTOKEN", "ENCRYPTED-SECRET"):
        assert secret not in stored


def test_signing_key_registration_and_retirement_are_recorded(factory):
    key_id = new_id("att")
    with factory() as db:
        db.add(AttestationKey(key_id=key_id, alg="Ed25519", public_key="A" * 43, status="active",
                              created_at_ms=NOW))
        db.commit()
        row = db.get(AttestationKey, key_id)
        row.status, row.retired_at_ms = "retired", NOW + 1
        db.commit()
        rows = events(db, target_id=key_id)
    assert [e.action for e in rows] == ["signing_key.registered", "signing_key.retired"]
    assert "A" * 43 not in json.dumps([e.details for e in rows])  # public, but not needed either


def test_a_change_that_is_rolled_back_leaves_no_record(factory, partner_id):
    with factory() as db:
        before = len(events(db, partner_id=partner_id))
        db.add(new_key(partner_id))
        db.flush()  # written, but not committed
        db.rollback()
        assert len(events(db, partner_id=partner_id)) == before


def test_the_record_and_the_change_commit_together(factory, partner_id):
    """If the audit row cannot be written, the change must not be saved either."""
    key = new_key(partner_id)
    with factory() as db:
        db.add(key)
        # `action` is NOT NULL, so this row cannot be saved:
        db.add(AuditEvent(at_ms=NOW, action=None, actor_type="system", target_type="t", details={}))
        with pytest.raises(DBAPIError):
            db.commit()
        db.rollback()
    with factory() as db:
        assert db.get(ApiKey, key.id) is None


def test_every_recorded_action_is_in_the_published_list(factory, partner_id):
    with factory() as db:
        db.add(new_key(partner_id))
        db.commit()
        seen = {e.action for e in events(db)}
    assert seen <= set(ACTIONS)


def test_a_committed_change_writes_one_log_line_with_the_request_id(factory, partner_id):
    key = new_key(partner_id)
    with capture_logs() as lines:
        with factory() as db:
            audit.set_actor(db, "api_key", "key_admin")
            audit.set_context(db, request_id="req_feedfacefeedface")
            db.add(key)
            db.commit()
    mine = [e for e in lines() if e["logger"] == "certivo.audit" and e.get("target_id") == key.id]
    assert len(mine) == 1
    assert mine[0]["action"] == "api_key.created" and mine[0]["request_id"] == "req_feedfacefeedface"
    assert mine[0]["actor_id"] == "key_admin"


def test_a_rolled_back_change_writes_no_log_line(factory, partner_id):
    key = new_key(partner_id)
    with capture_logs() as lines:
        with factory() as db:
            db.add(key)
            db.flush()
            db.rollback()
    assert [e for e in lines() if e.get("target_id") == key.id] == []


# ------------------------------------------------------------------ append-only

def _one_event(factory, partner_id):
    with factory() as db:
        db.add(new_key(partner_id))
        db.commit()
        return events(db, partner_id=partner_id)[-1].id


def test_the_application_cannot_edit_or_delete_an_audit_record(factory, partner_id):
    event_id = _one_event(factory, partner_id)
    with factory() as db:
        event = db.get(AuditEvent, event_id)
        event.action = "api_key.nothing_happened"
        with pytest.raises(AuditImmutableError):
            db.commit()
        db.rollback()
        db.delete(db.get(AuditEvent, event_id))
        with pytest.raises(AuditImmutableError):
            db.commit()
        db.rollback()


def test_the_database_refuses_to_update_an_audit_record(factory, partner_id):
    event_id = _one_event(factory, partner_id)
    with factory() as db:
        with pytest.raises(DBAPIError, match="append-only"):
            db.execute(text("UPDATE audit_events SET action = 'tampered' WHERE id = :i"), {"i": event_id})
        db.rollback()
        assert db.get(AuditEvent, event_id).action != "tampered"


def test_the_database_refuses_to_delete_an_audit_record(factory, partner_id):
    event_id = _one_event(factory, partner_id)
    with factory() as db:
        with pytest.raises(DBAPIError, match="append-only"):
            db.execute(text("DELETE FROM audit_events WHERE id = :i"), {"i": event_id})
        db.rollback()
        assert db.get(AuditEvent, event_id) is not None


def test_the_database_refuses_to_empty_the_audit_log(factory, partner_id):
    _one_event(factory, partner_id)
    with factory() as db:
        if db.get_bind().dialect.name != "postgresql":
            pytest.skip("TRUNCATE only exists on Postgres; SQLite has no such statement")
        with pytest.raises(DBAPIError, match="append-only"):
            db.execute(text("TRUNCATE audit_events"))
        db.rollback()
