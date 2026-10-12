"""Build step P0-06: scoped and revocable keys, expiring tokens, rate limits, size limits,
security headers and CORS. Each test proves one promise made in docs/spec/base/01 and 02."""
import asyncio
import json

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app.admin import create_partner
from app.config import Settings
from app.db import make_engine
from app.hardening import BodyLimitMiddleware  # noqa: F401  (documented entry point)
from app.models import ApiKey
from app.ratelimit import RateLimiter
from app.sandbox import make_signed_packet
from app.security import sha256_hex
from tests.conftest import T0


def new_key(client, headers, scopes, name="test key"):
    r = client.post("/v1/api-keys", json={"name": name, "scopes": scopes}, headers=headers)
    assert r.status_code == 201, r.text
    body = r.json()
    return body, {"Authorization": f"Bearer {body['key']}"}


def partner_headers(app, name="P"):
    with app.state.session_factory() as db:
        partner, raw = create_partner(db, name)
    return partner, {"Authorization": f"Bearer {raw}"}


def code_of(response):
    return response.json()["error"]["code"]


# ------------------------------------------------------------------ scopes and key lifecycle

def test_new_key_is_shown_once_and_stored_only_as_a_hash(client, auth, app):
    body, _ = new_key(client, auth, ["sessions:read"])
    assert body["key"].startswith("cvk_") and body["key_prefix"] == body["key"][:12]
    listing = client.get("/v1/api-keys", headers=auth).json()["data"]
    assert all("key" not in k and "key_hash" not in k for k in listing)
    with app.state.session_factory() as db:
        row = db.get(ApiKey, body["id"])
    assert row.key_hash == sha256_hex(body["key"])
    assert body["key"] not in {str(v) for v in vars(row).values()}


@pytest.mark.parametrize("method,path,payload,scope", [
    ("POST", "/v1/devices", {"public_key": "A" * 43}, "devices:write"),
    ("GET", "/v1/devices/dev_x", None, "devices:read"),
    ("DELETE", "/v1/devices/dev_x", None, "devices:write"),
    ("POST", "/v1/sessions/continuous", {"use_case": "default_video_call"}, "sessions:write"),
    ("POST", "/v1/sessions/continuous/cs_x/end", None, "sessions:write"),
    ("POST", "/v1/api-keys", {"name": "x", "scopes": ["sessions:read"]}, "keys:admin"),
    ("GET", "/v1/api-keys", None, "keys:admin"),
    ("DELETE", "/v1/api-keys/key_x", None, "keys:admin"),
])
def test_a_key_without_the_needed_scope_gets_403(client, auth, method, path, payload, scope):
    _, headers = new_key(client, auth, ["sessions:read"])
    r = client.request(method, path, json=payload, headers=headers)
    assert r.status_code == 403 and code_of(r) == "forbidden_scope"
    assert f"'{scope}'" in r.json()["error"]["message"]


def test_a_read_only_key_can_read_but_not_write(client, auth, session):
    sess, _ = session
    _, headers = new_key(client, auth, ["sessions:read"])
    assert client.get(f"/v1/sessions/continuous/{sess['id']}/status", headers=headers).status_code == 200
    assert client.post(f"/v1/sessions/continuous/{sess['id']}/end", headers=headers).status_code == 403


def test_a_key_cannot_grant_scopes_it_does_not_hold(client, auth):
    _, helper = new_key(client, auth, ["keys:admin", "sessions:read"])
    r = client.post("/v1/api-keys", json={"name": "greedy", "scopes": ["devices:write"]},
                    headers=helper)
    assert r.status_code == 403 and code_of(r) == "forbidden_scope"
    ok = client.post("/v1/api-keys", json={"name": "fine", "scopes": ["sessions:read"]},
                     headers=helper)
    assert ok.status_code == 201


@pytest.mark.parametrize("payload", [
    {"name": "x", "scopes": []},
    {"name": "x", "scopes": ["sessions:read", "sessions:read"]},
    {"name": "x", "scopes": ["root"]},
    {"name": "bad/name", "scopes": ["sessions:read"]},
    {"name": "x", "scopes": ["sessions:read"], "extra": 1},
])
def test_key_creation_rejects_bad_input(client, auth, payload):
    r = client.post("/v1/api-keys", json=payload, headers=auth)
    assert r.status_code == 422 and code_of(r) == "validation_error"


def test_the_number_of_active_keys_is_capped(make_app):
    app = make_app(max_api_keys_per_partner=3)
    from fastapi.testclient import TestClient
    client = TestClient(app)
    _, admin = partner_headers(app)
    first, _ = new_key(client, admin, ["sessions:read"])
    new_key(client, admin, ["sessions:read"])  # the initial key plus two = the cap of 3
    r = client.post("/v1/api-keys", json={"name": "one too many", "scopes": ["sessions:read"]},
                    headers=admin)
    assert r.status_code == 409 and code_of(r) == "api_key_limit_reached"
    assert client.delete(f"/v1/api-keys/{first['id']}", headers=admin).status_code == 204
    assert new_key(client, admin, ["sessions:read"])[0]["id"]  # room again after a revoke


def test_a_revoked_key_stops_working_immediately(client, auth, app):
    body, key_headers = new_key(client, auth, ["sessions:read"])
    assert client.get("/v1/api-keys", headers=auth).status_code == 200
    assert client.get("/v1/sessions/continuous/cs_x/status", headers=key_headers).status_code == 404
    assert client.delete(f"/v1/api-keys/{body['id']}", headers=auth).status_code == 204
    r = client.get("/v1/sessions/continuous/cs_x/status", headers=key_headers)
    assert r.status_code == 401 and code_of(r) == "invalid_api_key"
    again = client.delete(f"/v1/api-keys/{body['id']}", headers=auth)  # revoking twice is harmless
    assert again.status_code == 204
    shown = next(k for k in client.get("/v1/api-keys", headers=auth).json()["data"]
                 if k["id"] == body["id"])
    assert shown["active"] is False and shown["revoked_at_ms"] is not None


def test_keys_rotate_without_downtime(client, auth):
    old, old_headers = new_key(client, auth, ["sessions:read"], name="old")
    new, new_headers = new_key(client, auth, ["sessions:read"], name="new")
    for headers in (old_headers, new_headers):  # both work during the overlap
        assert client.get("/v1/sessions/continuous/cs_x/status", headers=headers).status_code == 404
    client.delete(f"/v1/api-keys/{old['id']}", headers=auth)
    assert client.get("/v1/sessions/continuous/cs_x/status", headers=old_headers).status_code == 401
    assert client.get("/v1/sessions/continuous/cs_x/status", headers=new_headers).status_code == 404


def test_one_partner_cannot_see_or_revoke_anothers_keys(client, auth, other_auth):
    mine, _ = new_key(client, auth, ["sessions:read"])
    r = client.delete(f"/v1/api-keys/{mine['id']}", headers=other_auth)
    assert r.status_code == 404 and code_of(r) == "api_key_not_found"
    theirs = client.get("/v1/api-keys", headers=other_auth).json()["data"]
    assert mine["id"] not in {k["id"] for k in theirs}


def test_last_use_is_recorded_at_most_once_a_minute(client, auth, app, clock):
    def last_used():
        keys = client.get("/v1/api-keys", headers=auth).json()["data"]
        return keys[0]["last_used_at_ms"]
    assert last_used() == T0  # the listing call itself recorded the first use
    clock.t += 30_000
    client.get("/v1/api-keys", headers=auth)
    assert last_used() == T0  # under a minute later: not rewritten
    clock.t += 31_000
    client.get("/v1/api-keys", headers=auth)
    assert last_used() == T0 + 61_000


# ------------------------------------------------------------------ SDK tokens and devices

def test_the_sdk_token_expires_and_the_response_says_when(make_app, auth):
    from fastapi.testclient import TestClient
    app = make_app(sdk_token_ttl_seconds=100)
    client = TestClient(app)
    _, admin = partner_headers(app)
    s = client.post("/v1/sessions/continuous", headers=admin,
                    json={"use_case": "default_video_call"}).json()
    assert s["sdk_token_expires_at_ms"] == T0 + 100_000
    sdk = {"Authorization": f"Bearer {s['sdk_token']}"}
    pause = f"/internal/v1/sessions/continuous/{s['id']}/pause"
    resume = f"/internal/v1/sessions/continuous/{s['id']}/resume"
    assert client.post(pause, headers=sdk).status_code == 204  # fine before expiry
    app.state.clock.t += 100_000  # exactly at the expiry time
    for url in (pause, resume, f"/internal/v1/sessions/continuous/{s['id']}/score-events"):
        r = client.post(url, headers=sdk, json={})
        assert r.status_code == 401 and code_of(r) == "session_token_expired", url


def test_an_expired_token_fails_even_with_a_valid_signed_packet(make_app, device):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from fastapi.testclient import TestClient

    from app.crypto import public_key_b64u
    app = make_app(sdk_token_ttl_seconds=10)
    client = TestClient(app)
    _, admin = partner_headers(app)
    key = Ed25519PrivateKey.generate()
    dev = client.post("/v1/devices", headers=admin, json={"public_key": public_key_b64u(key)}).json()
    s = client.post("/v1/sessions/continuous", headers=admin,
                    json={"use_case": "default_video_call"}).json()
    app.state.clock.t += 11_000
    packet = make_signed_packet(key, s["id"], dev["id"], "alice", 0, T0, T0 + 1000, 900)
    r = client.post(f"/internal/v1/sessions/continuous/{s['id']}/score-events", json=packet,
                    headers={"Authorization": f"Bearer {s['sdk_token']}"})
    assert r.status_code == 401 and code_of(r) == "session_token_expired"


def test_the_sdk_token_is_dead_once_the_session_ends(client, auth, session):
    sess, sdk = session
    client.post(f"/v1/sessions/continuous/{sess['id']}/end", headers=auth)
    for action in ("pause", "resume"):
        r = client.post(f"/internal/v1/sessions/continuous/{sess['id']}/{action}", headers=sdk)
        assert r.status_code == 409 and code_of(r) == "session_not_active"


def test_a_revoked_device_is_refused_immediately(client, auth, device, session):
    sess, sdk = session
    key, dev_id = device
    url = f"/internal/v1/sessions/continuous/{sess['id']}/score-events"
    packet = make_signed_packet(key, sess["id"], dev_id, "alice", 0, T0 - 2000, T0 - 1000, 900)
    assert client.post(url, json=packet, headers=sdk).status_code == 200
    assert client.delete(f"/v1/devices/{dev_id}", headers=auth).status_code == 204
    assert client.get(f"/v1/devices/{dev_id}", headers=auth).json()["status"] == "revoked"
    later = make_signed_packet(key, sess["id"], dev_id, "alice", 1, T0 - 1000, T0, 900)
    r = client.post(url, json=later, headers=sdk)
    assert r.status_code == 401 and code_of(r) == "invalid_device_signature"
    assert client.delete(f"/v1/devices/{dev_id}", headers=auth).status_code == 204  # harmless again


def test_revoking_one_device_leaves_others_working(client, auth, session):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    from app.crypto import public_key_b64u
    sess, sdk = session
    keys = [Ed25519PrivateKey.generate() for _ in range(2)]
    ids = [client.post("/v1/devices", headers=auth, json={"public_key": public_key_b64u(k)}).json()["id"]
           for k in keys]
    client.delete(f"/v1/devices/{ids[0]}", headers=auth)
    url = f"/internal/v1/sessions/continuous/{sess['id']}/score-events"
    good = make_signed_packet(keys[1], sess["id"], ids[1], "bob", 0, T0 - 2000, T0 - 1000, 900)
    assert client.post(url, json=good, headers=sdk).status_code == 200


def test_one_partner_cannot_revoke_anothers_device(client, other_auth, device):
    r = client.delete(f"/v1/devices/{device[1]}", headers=other_auth)
    assert r.status_code == 404 and code_of(r) == "device_not_found"


# ------------------------------------------------------------------ rate limits

def test_the_key_limit_returns_429_with_a_stable_code_and_headers(make_app):
    from fastapi.testclient import TestClient
    app = make_app(rate_limit_key_per_minute=3)
    client = TestClient(app)
    _, admin = partner_headers(app)
    for expected_remaining in ("2", "1", "0"):
        r = client.get("/v1/api-keys", headers=admin)
        assert r.status_code == 200
        assert r.headers["ratelimit-limit"] == "3" and r.headers["ratelimit-remaining"] == expected_remaining
    blocked = client.get("/v1/api-keys", headers=admin)
    assert blocked.status_code == 429 and code_of(blocked) == "rate_limited"
    retry_after = int(blocked.headers["retry-after"])
    assert 0 < retry_after <= 21
    assert blocked.headers["ratelimit-remaining"] == "0" and int(blocked.headers["ratelimit-reset"]) > 0
    assert blocked.json()["error"]["request_id"] == blocked.headers["x-request-id"]
    app.state.clock.t += retry_after * 1000  # wait as told, and it works again
    assert client.get("/v1/api-keys", headers=admin).status_code == 200


def test_limits_are_per_key(make_app):
    from fastapi.testclient import TestClient
    app = make_app(rate_limit_key_per_minute=2)
    client = TestClient(app)
    _, admin = partner_headers(app)
    # the creation call spends one request of the admin key's budget
    _, second = new_key(client, admin, ["keys:admin"])
    for _ in range(2):
        assert client.get("/v1/api-keys", headers=second).status_code == 200
    assert client.get("/v1/api-keys", headers=second).status_code == 429
    assert client.get("/v1/api-keys", headers=admin).status_code == 200  # the other key is unaffected


def test_the_session_limit_is_separate_from_the_key_limit(make_app):
    from fastapi.testclient import TestClient
    app = make_app(rate_limit_session_per_minute=2)
    client = TestClient(app)
    _, admin = partner_headers(app)
    sessions = [client.post("/v1/sessions/continuous", headers=admin,
                            json={"use_case": "default_video_call"}).json() for _ in range(2)]
    def pause(s):
        return client.post(f"/internal/v1/sessions/continuous/{s['id']}/pause",
                           headers={"Authorization": f"Bearer {s['sdk_token']}"})
    assert [pause(sessions[0]).status_code for _ in range(2)] == [204, 204]
    blocked = pause(sessions[0])
    assert blocked.status_code == 429 and code_of(blocked) == "rate_limited"
    assert pause(sessions[1]).status_code == 204  # a different session is unaffected
    assert client.get(f"/v1/sessions/continuous/{sessions[0]['id']}/status",
                      headers=admin).status_code == 200  # and so is the partner's own key


def test_repeated_failed_logins_from_one_address_are_throttled(make_app):
    from fastapi.testclient import TestClient
    app = make_app(rate_limit_auth_failures_per_minute=3)
    client = TestClient(app)
    _, admin = partner_headers(app)
    for i in range(3):
        r = client.get("/v1/api-keys", headers={"Authorization": f"Bearer cvk_wrong{i:02d}"})
        assert r.status_code == 401 and code_of(r) == "invalid_api_key"
    # now even a correct key from this address is refused, which is what slows a guessing attack
    blocked = client.get("/v1/api-keys", headers=admin)
    assert blocked.status_code == 429 and code_of(blocked) == "rate_limited"
    app.state.clock.t += 60_000
    assert client.get("/v1/api-keys", headers=admin).status_code == 200


def test_failed_sdk_token_guesses_are_throttled_too(make_app):
    from fastapi.testclient import TestClient
    app = make_app(rate_limit_auth_failures_per_minute=2)
    client = TestClient(app)
    _, admin = partner_headers(app)
    s = client.post("/v1/sessions/continuous", headers=admin,
                    json={"use_case": "default_video_call"}).json()
    url = f"/internal/v1/sessions/continuous/{s['id']}/pause"
    for i in range(2):
        assert client.post(url, headers={"Authorization": f"Bearer skt_guess{i}"}).status_code == 401
    r = client.post(url, headers={"Authorization": f"Bearer {s['sdk_token']}"})
    assert r.status_code == 429


def test_x_forwarded_for_is_ignored_unless_proxies_are_trusted(make_app):
    from fastapi.testclient import TestClient
    app = make_app(rate_limit_auth_failures_per_minute=2, trusted_proxy_hops=0)
    client = TestClient(app)
    for i in range(2):
        client.get("/v1/api-keys", headers={"Authorization": "Bearer cvk_bad",
                                            "X-Forwarded-For": f"203.0.113.{i}"})
    r = client.get("/v1/api-keys", headers={"Authorization": "Bearer cvk_bad2",
                                            "X-Forwarded-For": "203.0.113.99"})
    assert r.status_code == 429  # a spoofed header did not buy a fresh allowance


def test_x_forwarded_for_is_used_when_one_proxy_is_trusted(make_app):
    from fastapi.testclient import TestClient
    app = make_app(rate_limit_auth_failures_per_minute=2, trusted_proxy_hops=1)
    client = TestClient(app)
    _, admin = partner_headers(app)
    attacker = {"X-Forwarded-For": "198.51.100.7"}
    for i in range(2):
        client.get("/v1/api-keys", headers={"Authorization": f"Bearer cvk_bad{i}", **attacker})
    assert client.get("/v1/api-keys", headers={**admin, **attacker}).status_code == 429
    other = {"X-Forwarded-For": "198.51.100.8"}  # a different real client is not punished
    assert client.get("/v1/api-keys", headers={**admin, **other}).status_code == 200


def test_the_token_bucket_math():
    t = {"now": 0}
    limiter = RateLimiter(lambda: t["now"])
    first = limiter.check("k", 60)  # 60 per minute = one per second
    assert first.allowed and first.remaining == 59 and first.limit == 60
    peek = limiter.check("k", 60, consume=False)
    assert peek.remaining == 59  # looking does not spend
    for _ in range(59):
        assert limiter.check("k", 60).allowed
    empty = limiter.check("k", 60)
    assert not empty.allowed and empty.remaining == 0 and empty.retry_after_s == 1
    t["now"] += 1000
    assert limiter.check("k", 60).allowed  # one second later, one more request
    assert not limiter.check("k", 60).allowed
    assert limiter.check("other", 60).allowed  # buckets are independent


def test_idle_buckets_are_forgotten():
    t = {"now": 0}
    limiter = RateLimiter(lambda: t["now"])
    for i in range(10):
        limiter.check(f"k{i}", 60)
    t["now"] += 120_000
    limiter._prune(t["now"])
    assert limiter._buckets == {}


# ------------------------------------------------------------------ request size and speed

def test_an_oversized_declared_body_is_refused_with_413(make_app):
    from fastapi.testclient import TestClient
    client = TestClient(make_app(max_body_bytes=1000))
    r = client.post("/v1/devices", content=b"x" * 2000,
                    headers={"Content-Type": "application/json"})  # no credentials needed to be refused
    assert r.status_code == 413 and code_of(r) == "payload_too_large"
    assert r.json()["error"]["request_id"] == r.headers["x-request-id"]


def test_a_streamed_oversized_body_is_refused_too(make_app):
    from fastapi.testclient import TestClient
    client = TestClient(make_app(max_body_bytes=1000))

    def chunks():  # sent with no Content-Length: the size is only discovered while reading
        for _ in range(3):
            yield b"x" * 600
    r = client.post("/v1/devices", content=chunks(), headers={"Content-Type": "application/json"})
    assert r.status_code == 413 and code_of(r) == "payload_too_large"


def test_a_body_under_the_limit_is_still_handled_normally(make_app):
    from fastapi.testclient import TestClient
    app = make_app(max_body_bytes=1000)
    client = TestClient(app)
    _, admin = partner_headers(app)
    r = client.post("/v1/devices", headers=admin, content=b'{"public_key": "' + b"A" * 40 + b'"}')
    assert r.status_code == 422 and code_of(r) == "validation_error"  # reached the endpoint, not 413


def test_the_default_limit_is_64_kib(app, client, auth):
    assert app.state.settings.max_body_bytes == 65_536
    big = client.post("/v1/devices", content=b"x" * 70_000, headers=auth)
    assert big.status_code == 413
    ok = client.post("/v1/devices", content=b"x" * 60_000, headers={**auth, "Content-Type": "application/json"})
    assert ok.status_code == 422  # large but allowed


def call_asgi(app, receive, path="/v1/devices"):
    sent = []

    async def send(message):
        sent.append(message)

    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "POST",
             "path": path, "raw_path": path.encode(), "query_string": b"", "root_path": "",
             "headers": [(b"content-type", b"application/json")], "scheme": "http",
             "client": ("203.0.113.9", 5000), "server": ("test", 80)}
    asyncio.run(app(scope, receive, send))
    status = next(m["status"] for m in sent if m["type"] == "http.response.start")
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    return status, json.loads(body)


def test_a_body_that_stalls_gets_408(make_app):
    app = make_app(body_read_timeout_s=0.05)
    calls = {"n": 0}

    async def receive():
        calls["n"] += 1
        if calls["n"] == 1:
            return {"type": "http.request", "body": b'{"public_key": "', "more_body": True}
        await asyncio.sleep(5)  # the client goes quiet mid-body
        return {"type": "http.request", "body": b"", "more_body": False}

    status, body = call_asgi(app, receive)
    assert status == 408 and body["error"]["code"] == "request_timeout"


def test_a_complete_body_is_not_subject_to_the_read_timeout(make_app):
    from fastapi.testclient import TestClient
    app = make_app(body_read_timeout_s=0.05)
    client = TestClient(app)
    _, admin = partner_headers(app)
    assert client.post("/v1/devices", headers=admin, json={"public_key": "A" * 43}).status_code == 201


def test_postgres_enforces_the_statement_timeout(db_url):
    if not db_url.startswith("postgresql"):
        pytest.skip("Postgres only")
    engine = make_engine(db_url, statement_timeout_ms=200)
    try:
        with engine.connect() as conn, pytest.raises(OperationalError):
            conn.execute(text("select pg_sleep(2)"))
    finally:
        engine.dispose()


# ------------------------------------------------------------------ headers, docs and CORS

SECURITY = {"x-content-type-options": "nosniff", "x-frame-options": "DENY",
            "referrer-policy": "no-referrer", "cache-control": "no-store"}


def test_security_headers_are_on_every_kind_of_response(client, auth):
    responses = [client.get("/healthz"), client.get("/no/such/page"),
                 client.get("/v1/api-keys"), client.get("/v1/api-keys", headers=auth)]
    for r in responses:
        for name, value in SECURITY.items():
            assert r.headers[name] == value, (r.url, name)
        assert r.headers["content-security-policy"] == "default-src 'none'; frame-ancestors 'none'"
        assert r.headers["x-request-id"].startswith("req_")


def test_hsts_is_sent_outside_dev_only(make_app, client):
    from fastapi.testclient import TestClient
    assert "strict-transport-security" not in client.get("/healthz").headers
    staging = TestClient(make_app(env="staging"))
    assert "max-age=31536000" in staging.get("/healthz").headers["strict-transport-security"]


def test_interactive_docs_are_a_dev_convenience_only(make_app, client):
    from fastapi.testclient import TestClient
    docs = client.get("/docs")
    assert docs.status_code == 200 and "content-security-policy" not in docs.headers
    staging = TestClient(make_app(env="staging"))
    assert staging.get("/docs").status_code == 404
    assert staging.get("/openapi.json").status_code == 404
    forced = TestClient(make_app(env="staging", enable_docs=True))
    assert forced.get("/docs").status_code == 200


PREFLIGHT = {"Origin": "https://partner.example", "Access-Control-Request-Method": "POST",
             "Access-Control-Request-Headers": "authorization,content-type"}
SDK_URL = "/internal/v1/sessions/continuous/cs_x/score-events"


def test_no_browser_origin_is_allowed_by_default(client):
    r = client.options(SDK_URL, headers=PREFLIGHT)
    assert "access-control-allow-origin" not in r.headers


def test_a_configured_origin_may_call_the_sdk_endpoints(make_app):
    from fastapi.testclient import TestClient
    client = TestClient(make_app(env="staging", cors_allowed_origins="https://partner.example"))
    pre = client.options(SDK_URL, headers=PREFLIGHT)
    assert pre.status_code == 200
    assert pre.headers["access-control-allow-origin"] == "https://partner.example"
    assert "POST" in pre.headers["access-control-allow-methods"]
    assert "authorization" in pre.headers["access-control-allow-headers"].lower()
    assert "access-control-allow-credentials" not in pre.headers
    keys = client.get("/.well-known/certivo-keys", headers={"Origin": "https://partner.example"})
    assert keys.headers["access-control-allow-origin"] == "https://partner.example"
    assert "ratelimit-remaining" in keys.headers["access-control-expose-headers"].lower()


def test_an_unlisted_origin_is_refused(make_app):
    from fastapi.testclient import TestClient
    client = TestClient(make_app(env="staging", cors_allowed_origins="https://partner.example"))
    r = client.options(SDK_URL, headers={**PREFLIGHT, "Origin": "https://evil.example"})
    assert r.status_code == 400 and "access-control-allow-origin" not in r.headers


def test_the_partner_api_is_never_opened_to_browsers(make_app):
    from fastapi.testclient import TestClient
    client = TestClient(make_app(env="staging", cors_allowed_origins="https://partner.example"))
    r = client.options("/v1/api-keys", headers=PREFLIGHT)
    assert "access-control-allow-origin" not in r.headers


@pytest.mark.parametrize("env,origins", [
    ("staging", "*"), ("staging", "http://partner.example"), ("staging", "http://localhost:3000"),
    ("staging", "https://partner.example/path"), ("prod", "https://*.example.com"),
])
def test_unsafe_cors_settings_stop_the_app_from_starting(env, origins):
    with pytest.raises(ValueError, match="invalid origin"):
        Settings(env=env, cors_allowed_origins=origins, _env_file=None)


@pytest.mark.parametrize("env,origins", [
    ("dev", "*"), ("dev", "http://localhost:3000"), ("staging", "https://a.example,https://b.example:8443"),
])
def test_safe_cors_settings_are_accepted(env, origins):
    assert Settings(env=env, cors_allowed_origins=origins, _env_file=None).cors_origins


@pytest.mark.parametrize("field", ["max_body_bytes", "rate_limit_key_per_minute", "sdk_token_ttl_seconds"])
def test_nonsense_limits_are_rejected_at_startup(field):
    with pytest.raises(ValueError):
        Settings(_env_file=None, **{field: 0})
