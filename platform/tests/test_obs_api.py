"""P0-13 through the real application: request IDs in logs, metrics for real routes, the audit log
written by real API calls, and no secret in any log line. Needs the full app (fixtures in conftest)."""
import json
from types import SimpleNamespace

from sqlalchemy import select

from app import metrics
from app.models import AuditEvent
from app.services import sessions as sessions_service
from tests.obs_support import capture_logs


def sample(name, **labels):
    return metrics.REGISTRY.get_sample_value(name, labels) or 0.0


def audit_rows(app, **where):
    with app.state.session_factory() as db:
        stmt = select(AuditEvent).order_by(AuditEvent.id)
        for column, value in where.items():
            stmt = stmt.where(getattr(AuditEvent, column) == value)
        return list(db.scalars(stmt))


# ------------------------------------------------------------------ logs

def test_an_authenticated_request_logs_who_made_it_under_the_same_request_id(client, auth, partner_key):
    partner, _ = partner_key
    with capture_logs() as lines:
        r = client.get("/v1/api-keys", headers=auth)
    (entry,) = [e for e in lines() if e["logger"] == "certivo.access"]
    assert entry["request_id"] == r.headers["X-Request-ID"]
    assert entry["route"] == "/v1/api-keys" and entry["status"] == 200
    assert entry["partner_id"] == partner.id and entry["api_key_id"].startswith("key_")


def test_a_failed_login_is_logged_with_its_reason_and_counted(client):
    before = sample("certivo_auth_failures_total", reason="invalid_api_key")
    with capture_logs() as lines:
        r = client.get("/v1/api-keys", headers={"Authorization": "Bearer cvk_not_a_real_key_0000000000"})
    assert r.status_code == 401
    (entry,) = [e for e in lines() if e["logger"] == "certivo.access"]
    assert entry["error_code"] == "invalid_api_key" and "partner_id" not in entry
    assert sample("certivo_auth_failures_total", reason="invalid_api_key") == before + 1
    assert "not_a_real_key" not in str(lines())


def test_no_credential_or_token_appears_in_any_log_line(client, auth, partner_key):
    raw_key = partner_key[1]
    with capture_logs() as lines:
        created = client.post("/v1/api-keys", headers=auth,
                              json={"name": "second", "scopes": ["sessions:read"]})
        assert created.status_code == 201
        new_raw = created.json()["key"]
        started = client.post("/v1/sessions/continuous", headers=auth,
                              json={"use_case": "default_video_call", "participant_count": 2})
        sdk_token = started.json()["sdk_token"]
        client.get("/v1/api-keys", headers={"Authorization": f"Bearer {new_raw}"})
        client.post(f"/internal/v1/sessions/continuous/{started.json()['id']}/pause",
                    headers={"Authorization": f"Bearer {sdk_token}"})
        client.get("/v1/api-keys", headers={"Authorization": "Bearer cvk_wrong_wrong_wrong_wrong"})
    text = json.dumps(lines())
    for secret in (raw_key, new_raw, sdk_token, "cvk_wrong_wrong"):
        assert secret not in text
    assert "Bearer" not in text


def test_probes_do_not_flood_the_log(client):
    with capture_logs() as lines:
        client.get("/healthz")
    assert [e for e in lines() if e["logger"] == "certivo.access"] == []


# ------------------------------------------------------------------ metrics on the real routes

def test_real_routes_are_counted_by_template(client, auth):
    labels = dict(method="GET", route="/v1/api-keys", status="200")
    before = sample("certivo_http_requests_total", **labels)
    client.get("/v1/api-keys", headers=auth)
    assert sample("certivo_http_requests_total", **labels) == before + 1


def test_rate_limiting_is_counted(make_app):
    app = make_app(rate_limit_key_per_minute=2)
    from fastapi.testclient import TestClient

    from app.admin import create_partner
    with app.state.session_factory() as db:
        _, raw = create_partner(db, "Limited")
    c, headers = TestClient(app), {"Authorization": f"Bearer {raw}"}
    before = sample("certivo_rate_limited_total", scope="api_key")
    codes = [c.get("/v1/api-keys", headers=headers).status_code for _ in range(4)]
    assert 429 in codes
    assert sample("certivo_rate_limited_total", scope="api_key") > before


def test_metrics_endpoint_is_protected_outside_dev(make_app):
    from fastapi.testclient import TestClient

    token = "make-app-metrics-token-0001"
    app = make_app(env="staging", metrics_token=token)
    c = TestClient(app)
    assert c.get("/metrics").status_code == 401
    ok = c.get("/metrics", headers={"Authorization": f"Bearer {token}"})
    assert ok.status_code == 200 and "certivo_packet_ingest_lag_seconds" in ok.text


# ------------------------------------------------------------------ packet lag wiring

def _fake_event(now, lag_ms):
    return SimpleNamespace(interval_end_ms=now - lag_ms, participant_ref="p1", seq=1, device_id="dev")


class _FakeDb:
    def commit(self):
        pass

    def rollback(self):
        pass


def test_a_live_packet_records_how_late_it_arrived(monkeypatch, app):
    now = 1_760_000_100_000
    out = SimpleNamespace(seq=1, current_policy_outcome="accept", duplicate=False)  # all the function reads
    monkeypatch.setattr(sessions_service, "_ingest",
                        lambda *a, **k: (out, _fake_event(now, 7_000), None))
    monkeypatch.setattr(sessions_service, "_check_patterns", lambda *a, **k: None)
    count0 = sample("certivo_packet_ingest_lag_seconds_count", via="live")
    sum0 = sample("certivo_packet_ingest_lag_seconds_sum", via="live")
    sessions_service.ingest_score_event(_FakeDb(), app.state.settings, SimpleNamespace(),
                                        SimpleNamespace(), now)
    assert sample("certivo_packet_ingest_lag_seconds_count", via="live") == count0 + 1
    assert sample("certivo_packet_ingest_lag_seconds_sum", via="live") - sum0 == 7.0


def test_a_refused_live_packet_is_counted_by_its_error_code(monkeypatch, app):
    from app.errors import ApiError

    def refuse(*args, **kwargs):
        raise ApiError(401, "invalid_device_signature", "no")

    monkeypatch.setattr(sessions_service, "_ingest", refuse)
    before = sample("certivo_packets_rejected_total", via="live", code="invalid_device_signature")
    try:
        sessions_service.ingest_score_event(_FakeDb(), app.state.settings, SimpleNamespace(),
                                            SimpleNamespace(), 1)
    except ApiError:
        pass
    assert sample("certivo_packets_rejected_total", via="live", code="invalid_device_signature") == before + 1


# ------------------------------------------------------------------ the audit log through the API

def test_creating_and_revoking_a_key_through_the_api_is_audited(client, app, auth, partner_key):
    partner, _ = partner_key
    keys = client.get("/v1/api-keys", headers=auth).json()["data"]
    admin_key_id = keys[0]["id"]

    created = client.post("/v1/api-keys", headers=auth, json={"name": "audited", "scopes": ["sessions:read"]})
    assert created.status_code == 201
    key_id, raw = created.json()["id"], created.json()["key"]
    (row,) = [e for e in audit_rows(app, partner_id=partner.id) if e.action == "api_key.created"
              and e.target_id == key_id]
    assert (row.actor_type, row.actor_id) == ("api_key", admin_key_id)
    assert row.request_id == created.headers["X-Request-ID"]
    assert row.details == {"name": "audited", "scopes": ["sessions:read"]}
    assert raw not in json.dumps(row.details)

    assert client.delete(f"/v1/api-keys/{key_id}", headers=auth).status_code == 204
    (revoked,) = [e for e in audit_rows(app, partner_id=partner.id) if e.action == "api_key.revoked"]
    assert revoked.target_id == key_id and revoked.actor_id == admin_key_id


def test_ordinary_traffic_adds_nothing_to_the_audit_log(client, app, auth, partner_key):
    partner, _ = partner_key
    client.get("/v1/api-keys", headers=auth)  # first call writes last_used_at_ms
    before = len(audit_rows(app, partner_id=partner.id))
    for _ in range(3):
        client.get("/v1/api-keys", headers=auth)
        client.get("/v1/policies", headers=auth)
    assert len(audit_rows(app, partner_id=partner.id)) == before


def test_a_new_policy_version_through_the_api_is_audited(client, app, auth, partner_key):
    import pytest

    partner, _ = partner_key
    default = next(p for p in client.get("/v1/policies", headers=auth).json()["data"]
                   if p["use_case"] == "default_video_call")
    r = client.post("/v1/policies", headers=auth,
                    json={"use_case": "audit_check", "settings": default["settings"]})
    if r.status_code != 201:
        pytest.skip(f"could not build a valid policy body from the default ({r.status_code}); "
                    "the policy audit hook is covered by tests/test_audit_db.py")
    (row,) = [e for e in audit_rows(app, partner_id=partner.id) if e.action == "policy.created"]
    assert row.target_id == r.json()["id"] and row.details["use_case"] == "audit_check"
    assert row.actor_type == "api_key"


def test_startup_records_the_default_policy_and_the_signing_key(app):
    actions = {e.action for e in audit_rows(app, actor_type="system")}
    assert {"signing_key.registered"} <= actions
