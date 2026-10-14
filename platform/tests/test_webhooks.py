"""Build step P0-07: webhook delivery. Uses a real local server as the partner's endpoint."""
import datetime
import socket
import ssl

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.admin import create_partner
from app.config import Settings
from app.main import create_app
from app.models import WebhookDelivery, WebhookEndpoint, WebhookOutbox
from app.secretbox import SecretBox, load_secretbox
from app.webhook_engine import WebhookEngine
from app.webhook_sender import HttpSender, SendResult
from app.webhook_verify import ReplayGuard, parse_signature_header, verify_signature
from tests.conftest import SIGNING_KEY, T0, WEBHOOK_KEY
from tests.webhook_receiver import Receiver, Reply


def code_of(response):
    return response.json()["error"]["code"]


class World:
    """One app, one partner, one delivery engine, all sharing the test's fake clock."""

    def __init__(self, app, client, headers, engine, clock):
        self.app, self.client, self.headers, self.engine, self.clock = app, client, headers, engine, clock

    def add_endpoint(self, url, events=("*",), **extra):
        r = self.client.post("/v1/webhook-endpoints", headers=self.headers,
                             json={"url": url, "event_types": list(events), **extra})
        assert r.status_code == 201, r.text
        return r.json()

    def trigger_pause(self):
        s = self.client.post("/v1/sessions/continuous", headers=self.headers,
                             json={"use_case": "default_video_call"}).json()
        r = self.client.post(f"/internal/v1/sessions/continuous/{s['id']}/pause",
                             headers={"Authorization": f"Bearer {s['sdk_token']}"},
                             json={"reason": "connectivity"})
        assert r.status_code == 204
        return s["id"]

    def deliveries(self, **params):
        r = self.client.get("/v1/webhook-deliveries", headers=self.headers, params=params)
        assert r.status_code == 200, r.text
        return r.json()["data"]

    def only_delivery(self, **params):
        rows = self.deliveries(**params)
        assert len(rows) == 1, rows
        return rows[0]


@pytest.fixture
def receiver():
    r = Receiver().start()
    yield r
    r.stop()


@pytest.fixture
def make_world(make_app, clock):
    def factory(sender=None, **overrides):
        options = {"webhook_allow_private_targets": True, "webhook_retry_delays_s": "10,20",
                   "webhook_timeout_s": 2.0, **overrides}
        app = make_app(**options)
        client = TestClient(app)
        with app.state.session_factory() as db:
            _, raw = create_partner(db, "Hooks Partner")
        engine = WebhookEngine(app.state.settings, app.state.session_factory, clock,
                               app.state.secretbox, sender=sender)
        return World(app, client, {"Authorization": f"Bearer {raw}"}, engine, clock)
    return factory


# ------------------------------------------------------------------ managing endpoints

def test_the_signing_secret_is_shown_once_and_stored_encrypted(make_world, receiver):
    w = make_world()
    created = w.add_endpoint(receiver.url())
    assert created["secret"].startswith("whsec_") and created["status"] == "active"
    listing = w.client.get("/v1/webhook-endpoints", headers=w.headers).json()["data"]
    assert [e["id"] for e in listing] == [created["id"]] and "secret" not in listing[0]
    with w.app.state.session_factory() as db:
        row = db.get(WebhookEndpoint, created["id"])
    assert created["secret"] not in row.secret_encrypted  # not stored in clear
    assert w.app.state.secretbox.decrypt(row.secret_encrypted) == created["secret"]


@pytest.mark.parametrize("url", [
    "https://user:pass@hooks.example.com/x", "https://localhost/x", "https://127.0.0.1/x",
    "https://10.1.2.3/x", "https://169.254.169.254/latest/meta-data", "https://[::1]/x",
    "https://intranet/x", "https://billing.internal/x", "https://hooks.example.com/x#frag",
    "ftp://hooks.example.com/x", "https://hooks.example.com:99999/x", "https://hooks example.com/x",
    "https://" + "a" * 2050 + ".example.com/x",
])
def test_unsafe_urls_are_refused_at_registration(make_world, url):
    w = make_world(webhook_allow_private_targets=False)
    r = w.client.post("/v1/webhook-endpoints", headers=w.headers,
                      json={"url": url, "event_types": ["*"]})
    assert r.status_code in (422,) and code_of(r) in ("webhook_url_invalid", "validation_error")


def test_http_is_only_allowed_in_dev(make_world):
    dev = make_world(webhook_allow_private_targets=False)
    assert dev.client.post("/v1/webhook-endpoints", headers=dev.headers, json={
        "url": "http://hooks.example.com/x", "event_types": ["*"]}).status_code == 201
    staging = make_world(env="staging", webhook_allow_private_targets=False)
    r = staging.client.post("/v1/webhook-endpoints", headers=staging.headers, json={
        "url": "http://hooks.example.com/x", "event_types": ["*"]})
    assert r.status_code == 422 and code_of(r) == "webhook_url_invalid"


@pytest.mark.parametrize("events", [[], ["session.nonsense"], ["session.paused", "session.paused"],
                                    ["webhook.test"]])
def test_bad_event_lists_are_refused(make_world, events):
    w = make_world()
    r = w.client.post("/v1/webhook-endpoints", headers=w.headers,
                      json={"url": "https://hooks.example.com/x", "event_types": events})
    assert r.status_code == 422 and code_of(r) == "validation_error"


def test_choosing_everything_collapses_to_a_star(make_world):
    w = make_world()
    created = w.add_endpoint("https://hooks.example.com/x", events=("session.paused", "*"))
    assert created["event_types"] == ["*"]


def test_endpoints_need_the_webhook_scopes(make_world):
    w = make_world()
    keys = {}
    for name in ("webhooks:read", "sessions:read"):
        r = w.client.post("/v1/api-keys", headers=w.headers, json={"name": name, "scopes": [name]})
        keys[name] = {"Authorization": f"Bearer {r.json()['key']}"}
    body = {"url": "https://hooks.example.com/x", "event_types": ["*"]}
    assert w.client.post("/v1/webhook-endpoints", headers=keys["webhooks:read"], json=body).status_code == 403
    assert w.client.get("/v1/webhook-endpoints", headers=keys["webhooks:read"]).status_code == 200
    assert w.client.get("/v1/webhook-endpoints", headers=keys["sessions:read"]).status_code == 403
    assert w.client.get("/v1/webhook-deliveries", headers=keys["sessions:read"]).status_code == 403


def test_one_partner_cannot_touch_anothers_webhooks(make_world, receiver):
    w = make_world()
    created = w.add_endpoint(receiver.url())
    w.trigger_pause()
    w.engine.fan_out()
    delivery = w.only_delivery()
    with w.app.state.session_factory() as db:
        _, raw = create_partner(db, "Other")
    other = {"Authorization": f"Bearer {raw}"}
    eid = created["id"]
    for method, path in [("DELETE", f"/v1/webhook-endpoints/{eid}"),
                         ("POST", f"/v1/webhook-endpoints/{eid}/rotate-secret"),
                         ("POST", f"/v1/webhook-endpoints/{eid}/test")]:
        r = w.client.request(method, path, headers=other)
        assert r.status_code == 404 and code_of(r) == "webhook_endpoint_not_found", path
    r = w.client.post(f"/v1/webhook-deliveries/{delivery['id']}/retry", headers=other)
    assert r.status_code == 404 and code_of(r) == "webhook_delivery_not_found"
    assert w.client.get("/v1/webhook-endpoints", headers=other).json()["data"] == []
    assert w.client.get("/v1/webhook-deliveries", headers=other).json()["data"] == []


def test_the_number_of_endpoints_is_capped(make_world):
    w = make_world(webhook_max_endpoints_per_partner=2)
    w.add_endpoint("https://a.example.com/x")
    second = w.add_endpoint("https://b.example.com/x")
    r = w.client.post("/v1/webhook-endpoints", headers=w.headers,
                      json={"url": "https://c.example.com/x", "event_types": ["*"]})
    assert r.status_code == 409 and code_of(r) == "webhook_endpoint_limit_reached"
    assert w.client.delete(f"/v1/webhook-endpoints/{second['id']}", headers=w.headers).status_code == 204
    w.add_endpoint("https://c.example.com/x")


def test_deleting_an_endpoint_stops_everything_waiting_for_it(make_world, receiver):
    w = make_world()
    created = w.add_endpoint(receiver.url())
    w.trigger_pause()
    w.engine.fan_out()  # a delivery is now waiting
    assert w.client.delete(f"/v1/webhook-endpoints/{created['id']}", headers=w.headers).status_code == 204
    assert w.client.delete(f"/v1/webhook-endpoints/{created['id']}", headers=w.headers).status_code == 204
    assert w.client.get("/v1/webhook-endpoints", headers=w.headers).json()["data"] == []
    assert w.engine.run_once()["delivered"] == 0 and receiver.requests == []
    row = w.only_delivery()
    assert row["status"] == "dead" and row["last_error"] == "endpoint_deleted"
    for path in ("rotate-secret", "test"):
        assert w.client.post(f"/v1/webhook-endpoints/{created['id']}/{path}", headers=w.headers).status_code == 404


# ------------------------------------------------------------------ which events go where

def test_events_reach_only_subscribed_endpoints_of_the_same_partner(make_world, receiver):
    w = make_world()
    w.add_endpoint(receiver.url("/paused"), events=["session.paused"])
    w.add_endpoint(receiver.url("/dropped"), events=["session.confidence_dropped"])
    w.add_endpoint(receiver.url("/all"), events=["*"])
    with w.app.state.session_factory() as db:  # a second partner with its own catch-all endpoint
        _, raw = create_partner(db, "Another Partner")
    neighbour = {"Authorization": f"Bearer {raw}"}
    r = w.client.post("/v1/webhook-endpoints", headers=neighbour,
                      json={"url": receiver.url("/theirs"), "event_types": ["*"]})
    assert r.status_code == 201
    w.trigger_pause()  # an event for the FIRST partner only
    assert w.engine.fan_out() == 2
    assert w.engine.fan_out() == 0  # running it again creates no duplicates
    w.engine.run_once()
    assert sorted(x.path for x in receiver.requests) == ["/all", "/paused"]  # never /theirs
    assert len(w.deliveries()) == 2
    assert w.client.get("/v1/webhook-deliveries", headers=neighbour).json()["data"] == []


def test_an_event_from_before_an_endpoint_existed_is_not_sent_to_it(make_world, receiver):
    w = make_world()
    w.trigger_pause()
    w.engine.fan_out()  # nobody is listening yet
    w.add_endpoint(receiver.url())
    w.engine.run_once()
    assert receiver.requests == [] and w.deliveries() == []


def test_a_test_event_goes_to_exactly_one_endpoint(make_world, receiver):
    w = make_world()
    mine = w.add_endpoint(receiver.url("/mine"), events=["session.paused"])  # not even subscribed
    w.add_endpoint(receiver.url("/other"))
    r = w.client.post(f"/v1/webhook-endpoints/{mine['id']}/test", headers=w.headers)
    assert r.status_code == 202 and r.json()["event_id"].startswith("evt_")
    w.engine.run_once()
    assert [x.path for x in receiver.requests] == ["/mine"]
    body = receiver.requests[0].json
    assert body["type"] == "webhook.test" and body["data"] == {} and body["id"] == r.json()["event_id"]


# ------------------------------------------------------------------ the message and its signature

def test_a_delivery_is_signed_and_can_be_verified(make_world, receiver, clock):
    w = make_world()
    created = w.add_endpoint(receiver.url())
    session_id = w.trigger_pause()
    assert w.engine.run_once() == {"fanned_out": 1, "delivered": 1, "retrying": 0, "dead": 0, "skipped": 0}
    request = receiver.requests[0]
    body = request.json
    assert body["type"] == "session.paused" and body["api_version"] == "v1"
    assert body["data"]["session_id"] == session_id and body["data"]["reason"] == "connectivity"
    assert body["partner_id"].startswith("ptn_") and body["created_at_ms"] == T0
    h = request.headers
    assert h["certivo-event-id"] == body["id"] and h["certivo-event-type"] == "session.paused"
    assert h["content-type"] == "application/json" and h["user-agent"].startswith("Certivo-Webhooks/")
    assert h["host"] == f"127.0.0.1:{receiver.port}"
    assert verify_signature(created["secret"], h["certivo-signature"], request.body, clock.t)
    row = w.only_delivery()
    assert row["status"] == "delivered" and row["attempt_count"] == 1
    assert row["attempts"][0]["status_code"] == 200 and row["attempts"][0]["error"] is None


def test_a_careful_partner_rejects_replays_and_forgeries(make_world, clock):
    w = make_world()
    probe = Receiver().start()
    try:
        created = w.add_endpoint(probe.url())
        probe.verify_secret, probe.clock = created["secret"], lambda: clock.t
        w.trigger_pause()
        w.engine.run_once()
        assert len(probe.accepted) == 1 and w.only_delivery()["status"] == "delivered"
        captured = probe.requests[0]

        def resend(body=captured.body, header=captured.headers["certivo-signature"]):
            import httpx
            return httpx.post(probe.url(), content=body, headers={
                "Certivo-Signature": header, "Certivo-Event-Id": captured.headers["certivo-event-id"]}).status_code

        assert resend() == 409                                  # the same message again: a replay
        tampered = captured.body.replace(b"connectivity", b"other")
        assert resend(body=tampered) == 401                     # altered in transit
        clock.t += 301_000                                      # replayed after the window closes
        assert resend() == 401
        assert len(probe.accepted) == 1                         # nothing but the real one was acted on
    finally:
        probe.stop()


def test_a_careful_partner_still_accepts_the_retry_of_an_event_it_failed_on(make_world, clock):
    """Remembering an event only AFTER handling it successfully: otherwise a failure plus our retry
    would be mistaken for a duplicate and the event would be lost."""
    w = make_world()
    probe = Receiver().start()
    try:
        created = w.add_endpoint(probe.url())
        probe.verify_secret, probe.clock = created["secret"], lambda: clock.t
        probe.script = [Reply(500)]  # the partner's own handler fails the first time
        w.trigger_pause()
        w.engine.run_once()
        assert probe.accepted == [] and w.only_delivery()["status"] == "retrying"
        clock.t += 10_000
        w.engine.run_once()  # our retry carries the same event ID
        assert len(probe.accepted) == 1 and w.only_delivery()["status"] == "delivered"
    finally:
        probe.stop()


def test_a_message_signed_with_the_wrong_secret_is_refused():
    guard = ReplayGuard()
    assert guard.first_time("evt_1", 0) and not guard.first_time("evt_1", 1000)
    assert guard.first_time("evt_1", 49 * 3600 * 1000)  # forgotten after the retention period
    header = "t=1000,v1=" + "0" * 64
    assert not verify_signature("whsec_x", header, b"{}", 1000)
    assert not verify_signature("whsec_x", "garbage", b"{}", 1000)
    assert parse_signature_header("t=5,v1=aa,v1=bb") == (5, ["aa", "bb"])


def test_every_attempt_is_signed_with_a_fresh_timestamp(make_world, receiver, clock):
    w = make_world()
    created = w.add_endpoint(receiver.url())
    receiver.script = [Reply(500)]
    w.trigger_pause()
    w.engine.run_once()
    clock.t += 10_000
    w.engine.run_once()
    first, second = receiver.requests
    t1 = parse_signature_header(first.headers["certivo-signature"])[0]
    t2 = parse_signature_header(second.headers["certivo-signature"])[0]
    assert (t1, t2) == (T0, T0 + 10_000)
    for r, now in ((first, T0), (second, T0 + 10_000)):
        assert verify_signature(created["secret"], r.headers["certivo-signature"], r.body, now)


def test_during_rotation_both_secrets_sign_and_afterwards_only_the_new_one(make_world, receiver, clock):
    w = make_world(webhook_secret_overlap_s=3600)
    created = w.add_endpoint(receiver.url())
    old = created["secret"]
    rotated = w.client.post(f"/v1/webhook-endpoints/{created['id']}/rotate-secret", headers=w.headers).json()
    new = rotated["secret"]
    assert new != old and rotated["previous_secret_valid_until_ms"] == T0 + 3_600_000
    w.trigger_pause()
    w.engine.run_once()
    during = receiver.requests[0]
    assert len(parse_signature_header(during.headers["certivo-signature"])[1]) == 2
    for secret in (old, new):  # a partner can switch over without dropping messages
        assert verify_signature(secret, during.headers["certivo-signature"], during.body, clock.t)
    clock.t += 3_600_001
    w.trigger_pause()
    w.engine.run_once()
    after = receiver.requests[1]
    assert len(parse_signature_header(after.headers["certivo-signature"])[1]) == 1
    assert verify_signature(new, after.headers["certivo-signature"], after.body, clock.t)
    assert not verify_signature(old, after.headers["certivo-signature"], after.body, clock.t)


# ------------------------------------------------------------------ retries and the dead-letter state

def test_a_failing_endpoint_is_retried_with_growing_waits(make_world, receiver, clock):
    w = make_world(webhook_retry_delays_s="10,20")
    w.add_endpoint(receiver.url())
    receiver.script = [Reply(500), Reply(503)]
    w.trigger_pause()
    assert w.engine.run_once()["retrying"] == 1
    row = w.only_delivery()
    assert row["status"] == "retrying" and row["next_attempt_at_ms"] == T0 + 10_000
    assert row["last_status_code"] == 500 and row["last_error"] == "http_status"
    assert w.engine.run_once()["retrying"] == 0 and len(receiver.requests) == 1  # not due yet
    clock.t += 10_000
    assert w.engine.run_once()["retrying"] == 1
    assert w.only_delivery()["next_attempt_at_ms"] == T0 + 10_000 + 20_000  # the wait grew
    clock.t += 19_999
    assert w.engine.run_once()["delivered"] == 0 and len(receiver.requests) == 2  # still not due
    clock.t += 1
    assert w.engine.run_once()["delivered"] == 1
    row = w.only_delivery()
    assert row["status"] == "delivered" and row["attempt_count"] == 3
    assert [a["status_code"] for a in row["attempts"]] == [200, 503, 500]  # newest first
    assert row["next_attempt_at_ms"] is None


def test_when_every_attempt_fails_the_delivery_goes_to_the_dead_letter_state(make_world, receiver, clock):
    w = make_world(webhook_retry_delays_s="1,1")
    w.add_endpoint(receiver.url())
    receiver.default = Reply(500)
    w.trigger_pause()
    outcomes = []
    for _ in range(3):
        outcomes.append(next(k for k, v in w.engine.run_once().items() if k != "fanned_out" and v))
        clock.t += 1_000
    assert outcomes == ["retrying", "retrying", "dead"]
    row = w.only_delivery()
    assert row["status"] == "dead" and row["attempt_count"] == 3 and row["next_attempt_at_ms"] is None
    clock.t += 3_600_000
    assert w.engine.run_once() == {"fanned_out": 0, "delivered": 0, "retrying": 0, "dead": 0, "skipped": 0}
    assert len(receiver.requests) == 3  # a dead delivery is left alone
    assert [d["id"] for d in w.deliveries(status="dead")] == [row["id"]]
    assert w.deliveries(status="delivered") == []


def test_a_dead_delivery_can_be_retried_by_hand(make_world, receiver, clock):
    w = make_world(webhook_retry_delays_s="1")
    w.add_endpoint(receiver.url())
    receiver.default = Reply(500)
    w.trigger_pause()
    w.engine.run_once()
    clock.t += 1_000
    w.engine.run_once()
    row = w.only_delivery()
    assert row["status"] == "dead"
    receiver.default = Reply(200)  # the partner fixed their server
    r = w.client.post(f"/v1/webhook-deliveries/{row['id']}/retry", headers=w.headers)
    assert r.status_code == 202 and r.json()["status"] == "pending"
    assert w.engine.run_once()["delivered"] == 1
    done = w.only_delivery()
    assert done["status"] == "delivered" and done["attempt_count"] == 3
    again = w.client.post(f"/v1/webhook-deliveries/{row['id']}/retry", headers=w.headers)
    assert again.status_code == 409 and code_of(again) == "delivery_not_retryable"
    missing = w.client.post("/v1/webhook-deliveries/dlv_nope/retry", headers=w.headers)
    assert missing.status_code == 404 and code_of(missing) == "webhook_delivery_not_found"


def test_a_delivery_to_a_deleted_endpoint_cannot_be_retried(make_world, receiver, clock):
    w = make_world(webhook_retry_delays_s="1")
    created = w.add_endpoint(receiver.url())
    receiver.default = Reply(500)
    w.trigger_pause()
    w.engine.run_once()
    row = w.only_delivery()
    w.client.delete(f"/v1/webhook-endpoints/{created['id']}", headers=w.headers)
    r = w.client.post(f"/v1/webhook-deliveries/{row['id']}/retry", headers=w.headers)
    assert r.status_code == 409 and code_of(r) == "delivery_not_retryable"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_a_connection_that_is_refused_is_recorded_and_retried(make_world):
    w = make_world()
    w.add_endpoint(f"http://127.0.0.1:{free_port()}/hook")
    w.trigger_pause()
    assert w.engine.run_once()["retrying"] == 1
    row = w.only_delivery()
    assert row["last_error"] == "connection_error" and row["last_status_code"] is None


def test_a_partner_that_answers_too_slowly_times_out(make_world, receiver):
    w = make_world(webhook_timeout_s=0.2)
    w.add_endpoint(receiver.url())
    receiver.default = Reply(200, delay_s=1.0)
    w.trigger_pause()
    assert w.engine.run_once()["retrying"] == 1
    assert w.only_delivery()["last_error"] == "timeout"


def test_redirects_are_not_followed(make_world, receiver):
    w = make_world()
    w.add_endpoint(receiver.url())
    receiver.default = Reply(302, headers={"Location": receiver.url("/elsewhere")})
    w.trigger_pause()
    w.engine.run_once()
    row = w.only_delivery()
    assert row["last_error"] == "redirect" and row["last_status_code"] == 302
    assert [r.path for r in receiver.requests] == ["/hook"]  # the Location was never visited


def test_the_partners_reply_body_is_never_stored(make_world, receiver):
    w = make_world()
    w.add_endpoint(receiver.url())
    secret_text = b"internal-stack-trace-" * 5000
    receiver.default = Reply(500, body=secret_text)
    w.trigger_pause()
    w.engine.run_once()
    row = w.only_delivery()
    assert row["last_error"] == "http_status"
    assert "internal-stack-trace" not in str(row)
    with w.app.state.session_factory() as db:
        stored = db.scalars(select(WebhookDelivery)).one()
    assert all("internal-stack-trace" not in str(v) for v in vars(stored).values())


# ------------------------------------------------------------------ keeping our servers safe (SSRF)

@pytest.mark.parametrize("answer", [["127.0.0.1"], ["10.0.0.5"], ["169.254.169.254"], ["::1"],
                                    ["192.168.1.1"], ["93.184.216.34", "10.0.0.1"], ["::ffff:10.0.0.5"]])
def test_a_name_that_resolves_to_a_private_address_is_never_called(make_world, receiver, answer):
    sender = HttpSender(resolver=lambda host, port: answer)
    w = make_world(sender=sender, webhook_allow_private_targets=False)
    w.add_endpoint("https://partner.test/hook")  # looks fine at registration
    w.trigger_pause()
    assert w.engine.run_once()["retrying"] == 1
    assert w.only_delivery()["last_error"] == "blocked_address"
    assert receiver.requests == []


def test_a_name_that_does_not_resolve_is_a_dns_error(make_world):
    def broken(host, port):
        raise socket.gaierror("no such host")
    w = make_world(sender=HttpSender(resolver=broken), webhook_allow_private_targets=False)
    w.add_endpoint("https://partner.test/hook")
    w.trigger_pause()
    w.engine.run_once()
    assert w.only_delivery()["last_error"] == "dns_error"


def test_we_connect_to_the_address_we_checked_and_not_to_the_name_again(make_world, receiver):
    lookups = []

    def resolver(host, port):
        lookups.append(host)
        return ["127.0.0.1"]
    w = make_world(sender=HttpSender(resolver=resolver))  # dev: private targets allowed
    w.add_endpoint(f"http://partner.test:{receiver.port}/hook")
    w.trigger_pause()
    assert w.engine.run_once()["delivered"] == 1
    assert lookups == ["partner.test"]  # one lookup per attempt, so the name cannot change its answer
    assert receiver.requests[0].headers["host"] == f"partner.test:{receiver.port}"


def make_tls_material(tmp_path, hostname="localhost"):
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, hostname)])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName(hostname)]), critical=False)
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .sign(key, hashes.SHA256()))
    cert_file, key_file = tmp_path / "cert.pem", tmp_path / "key.pem"
    cert_file.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_file.write_bytes(key.private_bytes(serialization.Encoding.PEM,
                                           serialization.PrivateFormat.TraditionalOpenSSL,
                                           serialization.NoEncryption()))
    server = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server.load_cert_chain(cert_file, key_file)
    client = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    client.load_verify_locations(cafile=str(cert_file))
    return server, client


def test_https_is_checked_against_the_name_even_though_we_connect_to_the_address(make_world, tmp_path):
    server_ctx, client_ctx = make_tls_material(tmp_path)
    tls_receiver = Receiver(tls=server_ctx).start()
    try:
        sender = HttpSender(resolver=lambda host, port: ["127.0.0.1"], verify=client_ctx)
        w = make_world(sender=sender)
        w.add_endpoint(f"https://localhost:{tls_receiver.port}/hook")      # certificate is for localhost
        w.add_endpoint(f"https://impostor.test:{tls_receiver.port}/hook")  # certificate is NOT for this name
        w.trigger_pause()
        assert w.engine.run_once() == {"fanned_out": 2, "delivered": 1, "retrying": 1, "dead": 0, "skipped": 0}
        by_endpoint = {d["endpoint_id"]: d for d in w.deliveries()}
        good = next(d for d in by_endpoint.values() if d["status"] == "delivered")
        bad = next(d for d in by_endpoint.values() if d["status"] == "retrying")
        assert good["attempts"][0]["status_code"] == 200
        assert bad["last_error"] == "tls_error"
        assert len(tls_receiver.requests) == 1  # nothing was sent to the name that failed verification
    finally:
        tls_receiver.stop()


# ------------------------------------------------------------------ the engine's own safety rules

def make_one_delivery(w, receiver):
    w.add_endpoint(receiver.url())
    w.trigger_pause()
    w.engine.fan_out()


def test_a_delivery_can_only_be_claimed_by_one_worker_until_its_lock_runs_out(make_world, receiver, clock):
    w = make_world(webhook_lease_s=60)
    make_one_delivery(w, receiver)
    first = w.engine.claim_due()
    assert len(first) == 1 and w.engine.claim_due() == []  # a second worker gets nothing
    clock.t += 59_999
    assert w.engine.claim_due() == []
    clock.t += 2  # the first worker must have died: the lock ran out
    second = w.engine.claim_due()
    assert len(second) == 1 and second[0][1] != first[0][1]
    assert w.engine.attempt(*first[0]) == "skipped"  # the stale holder does nothing
    assert receiver.requests == []
    assert w.engine.attempt(*second[0]) == "delivered" and len(receiver.requests) == 1


def test_a_finished_delivery_cannot_be_sent_again_with_an_old_claim(make_world, receiver):
    w = make_world()
    make_one_delivery(w, receiver)
    (claim,) = w.engine.claim_due()
    assert w.engine.attempt(*claim) == "delivered"
    assert w.engine.attempt(*claim) == "skipped"
    assert len(receiver.requests) == 1


def test_a_result_arriving_after_the_delivery_was_settled_does_not_rewrite_it(make_world, receiver):
    holder = {}

    def sender_that_deletes_the_endpoint_mid_flight(*args, **kwargs):
        holder["world"].client.delete(f"/v1/webhook-endpoints/{holder['endpoint']}",
                                      headers=holder["world"].headers)
        return SendResult(200, None, 5)  # the partner answered fine, but too late to matter

    w = make_world(sender=sender_that_deletes_the_endpoint_mid_flight)
    holder.update(world=w, endpoint=w.add_endpoint(receiver.url())["id"])
    w.trigger_pause()
    w.engine.fan_out()
    (claim,) = w.engine.claim_due()
    assert w.engine.attempt(*claim) == "dead"
    row = w.only_delivery()
    assert row["status"] == "dead" and row["last_error"] == "endpoint_deleted"
    assert row["delivered_at_ms"] is None and len(row["attempts"]) == 1  # logged, not applied


def test_the_celery_tasks_do_the_same_work_through_the_worker_module(make_world, receiver):
    from app import worker
    w = make_world()
    w.add_endpoint(receiver.url())
    w.trigger_pause()
    assert {"certivo.webhooks.poll", "certivo.webhooks.deliver"} <= set(worker.celery_app.tasks)
    schedule = worker.celery_app.conf.beat_schedule["certivo-webhook-poll"]
    assert schedule["task"] == "certivo.webhooks.poll"
    worker.set_engine_for_tests(w.engine)
    worker.celery_app.conf.task_always_eager = True  # run tasks inline: no Redis needed for this test
    try:
        assert worker.poll.apply().get() == 1
    finally:
        worker.celery_app.conf.task_always_eager = False
        worker.set_engine_for_tests(None)
    assert len(receiver.requests) == 1 and w.only_delivery()["status"] == "delivered"


def test_the_delivery_list_pages_newest_first(make_world, receiver, clock):
    w = make_world()
    w.add_endpoint(receiver.url())
    for _ in range(5):
        w.trigger_pause()
        clock.t += 1_000
    w.engine.run_once()
    r = w.client.get("/v1/webhook-deliveries", headers=w.headers, params={"limit": 2})
    page1 = r.json()
    assert len(page1["data"]) == 2 and "next_cursor" in page1
    seen = [d["id"] for d in page1["data"]]
    cursor = page1["next_cursor"]
    while cursor:
        page = w.client.get("/v1/webhook-deliveries", headers=w.headers,
                            params={"limit": 2, "cursor": cursor}).json()
        seen += [d["id"] for d in page["data"]]
        cursor = page.get("next_cursor")
    assert len(seen) == 5 and len(set(seen)) == 5
    created = [d["created_at_ms"] for d in w.deliveries(limit=100)]
    assert created == sorted(created, reverse=True)
    bad = w.client.get("/v1/webhook-deliveries", headers=w.headers, params={"cursor": "not-a-cursor"})
    assert bad.status_code == 422 and code_of(bad) == "validation_error"
    assert w.client.get("/v1/webhook-deliveries", headers=w.headers, params={"limit": 101}).status_code == 422


# ------------------------------------------------------------------ secrets and settings

def test_the_secret_box_round_trips_and_refuses_the_wrong_key():
    box = SecretBox(WEBHOOK_KEY)
    token = box.encrypt("whsec_abc")
    assert token != "whsec_abc" and box.decrypt(token) == "whsec_abc"
    other = SecretBox(__import__("cryptography.fernet", fromlist=["Fernet"]).Fernet.generate_key())
    with pytest.raises(ValueError, match="wrong CERTIVO_WEBHOOK_SECRET_KEY"):
        other.decrypt(token)
    with pytest.raises(ValueError):
        SecretBox("not-a-valid-key")


def test_dev_has_a_fixed_fallback_key_and_everything_else_must_provide_one():
    dev_a = load_secretbox(Settings(_env_file=None))
    dev_b = load_secretbox(Settings(_env_file=None))
    assert dev_b.decrypt(dev_a.encrypt("same")) == "same"  # the API and the worker agree in dev
    with pytest.raises(RuntimeError, match="CERTIVO_WEBHOOK_SECRET_KEY is required"):
        load_secretbox(Settings(env="staging", _env_file=None))


def test_a_non_dev_app_will_not_start_without_the_webhook_key(db_url):
    settings = Settings(env="staging", database_url=db_url, attestation_signing_key=SIGNING_KEY,
                        _env_file=None)
    with pytest.raises(RuntimeError, match="WEBHOOK_SECRET_KEY"):
        create_app(settings)


@pytest.mark.parametrize("override", [
    {"webhook_retry_delays_s": "0,5"}, {"webhook_retry_delays_s": "a,b"},
    {"webhook_retry_delays_s": ""}, {"webhook_retry_delays_s": ",".join(["5"] * 13)},
    {"webhook_timeout_s": 30.0, "webhook_lease_s": 30},
    {"env": "staging", "webhook_allow_private_targets": True},
    {"webhook_max_endpoints_per_partner": 0},
])
def test_unsafe_webhook_settings_stop_the_app_from_starting(override):
    with pytest.raises(ValueError):
        Settings(_env_file=None, **override)


def test_the_outbox_is_written_with_the_change_that_caused_it(make_world, receiver):
    """An event exists if and only if its change was saved: that is what 'outbox' means."""
    w = make_world()
    w.trigger_pause()
    with w.app.state.session_factory() as db:
        events = list(db.scalars(select(WebhookOutbox)))
    assert [e.event_type for e in events] == ["session.paused"]
    assert events[0].event_id.startswith("evt_") and events[0].fanned_out_at_ms is None
