"""Request metrics, the structured access log, request IDs and GET /metrics (P0-13).

These tests use a small app with the REAL request pipeline, so they need no database."""
import logging

import pytest
from fastapi.testclient import TestClient

from app import metrics
from tests.obs_support import FAKE_API_KEY, FAKE_SDK_TOKEN, capture_logs, make_mini_app

TOKEN = "unit-test-metrics-token-0001"


def sample(name, **labels):
    return metrics.REGISTRY.get_sample_value(name, labels) or 0.0


@pytest.fixture
def client():
    app = make_mini_app(env="staging", metrics_token=TOKEN)
    return TestClient(app, raise_server_exceptions=False)


def access_lines(lines):
    return [entry for entry in lines if entry["logger"] == "certivo.access"]


# ------------------------------------------------------------------ request IDs

def test_every_response_carries_a_request_id_and_every_request_gets_its_own(client):
    first, second = client.get("/v1/things/a"), client.get("/v1/things/b")
    assert first.headers["X-Request-ID"].startswith("req_")
    assert first.headers["X-Request-ID"] != second.headers["X-Request-ID"]


def test_a_request_id_sent_by_the_caller_is_ignored(client):
    r = client.get("/v1/things/a", headers={"X-Request-ID": "req_chosen_by_attacker"})
    assert r.headers["X-Request-ID"] != "req_chosen_by_attacker"


def test_the_access_log_line_has_the_same_request_id_as_the_response(client):
    with capture_logs() as lines:
        r = client.get("/v1/things/a")
    (entry,) = access_lines(lines())
    assert entry["request_id"] == r.headers["X-Request-ID"]
    assert entry["method"] == "GET" and entry["status"] == 200
    assert entry["route"] == "/v1/things/{thing_id}" and entry["path"] == "/v1/things/a"
    assert entry["duration_ms"] >= 0


# ------------------------------------------------------------------ metrics

def test_requests_are_counted_by_route_template_not_by_raw_url(client):
    labels = dict(method="GET", route="/v1/things/{thing_id}", status="200")
    before = sample("certivo_http_requests_total", **labels)
    for thing in ("one", "two", "three"):
        client.get(f"/v1/things/{thing}")
    assert sample("certivo_http_requests_total", **labels) == before + 3
    exported = client.get("/metrics", headers={"Authorization": f"Bearer {TOKEN}"}).text
    assert "/v1/things/one" not in exported and "/v1/things/three" not in exported


def test_unknown_paths_share_one_label_so_scanners_cannot_flood_the_metrics(client):
    labels = dict(method="GET", route="unmatched", status="404")
    before = sample("certivo_http_requests_total", **labels)
    for n in range(5):
        client.get(f"/wp-admin/{n}")
    assert sample("certivo_http_requests_total", **labels) == before + 5


def test_unusual_http_methods_share_one_label(client):
    before = sample("certivo_http_requests_total", method="OTHER", route="unmatched", status="405") \
        + sample("certivo_http_requests_total", method="OTHER", route="unmatched", status="404")
    client.request("BREW", "/v1/things/a")
    after = sample("certivo_http_requests_total", method="OTHER", route="unmatched", status="405") \
        + sample("certivo_http_requests_total", method="OTHER", route="unmatched", status="404")
    assert after >= before  # whatever the status, it never created a BREW label
    assert "BREW" not in client.get("/metrics", headers={"Authorization": f"Bearer {TOKEN}"}).text


def test_latency_is_recorded(client):
    labels = dict(method="GET", route="/v1/things/{thing_id}")
    before = sample("certivo_http_request_duration_seconds_count", **labels)
    client.get("/v1/things/a")
    assert sample("certivo_http_request_duration_seconds_count", **labels) == before + 1


def test_a_refused_request_is_counted_and_its_error_code_is_logged(client):
    labels = dict(method="GET", route="/refused", status="409")
    before = sample("certivo_http_requests_total", **labels)
    with capture_logs() as lines:
        client.get("/refused")
    assert sample("certivo_http_requests_total", **labels) == before + 1
    (entry,) = access_lines(lines())
    assert entry["error_code"] == "seq_conflict" and entry["level"] == "INFO"


def test_a_crash_is_counted_as_a_500_logged_as_an_error_and_never_leaks_a_secret(client):
    labels = dict(method="GET", route="/boom", status="500")
    before = sample("certivo_http_requests_total", **labels)
    with capture_logs() as lines:
        r = client.get("/boom")
    assert r.status_code == 500
    assert r.json()["error"]["code"] == "internal_error"
    assert FAKE_SDK_TOKEN not in r.text  # nothing internal reaches the caller
    assert sample("certivo_http_requests_total", **labels) == before + 1
    logged = lines()
    assert FAKE_SDK_TOKEN not in str(logged)  # ... and the traceback in the log is scrubbed
    (access,) = access_lines(logged)
    assert access["level"] == "ERROR" and access["status"] == 500
    crash = next(e for e in logged if e["logger"] == "certivo.errors")
    assert crash["request_id"] == r.headers["X-Request-ID"] and "RuntimeError" in crash["exc"]


def test_validation_failures_log_their_error_code():
    app = make_mini_app(env="staging", metrics_token=TOKEN)

    @app.get("/needs-int/{n}")
    def needs_int(n: int):
        return {"n": n}

    with capture_logs() as lines:
        r = TestClient(app).get("/needs-int/abc")
    assert r.status_code == 422
    (entry,) = access_lines(lines())
    assert entry["error_code"] == "validation_error"


# ------------------------------------------------------------------ what the access log must NOT hold

def test_the_access_log_holds_no_credentials_headers_or_query_strings(client):
    with capture_logs() as lines:
        client.get(f"/v1/things/a?token={FAKE_SDK_TOKEN}&x=1",
                   headers={"Authorization": f"Bearer {FAKE_API_KEY}", "Cookie": "session=abc123"})
    text = str(lines())
    assert FAKE_API_KEY not in text and FAKE_SDK_TOKEN not in text
    assert "abc123" not in text and "token=" not in text and "x=1" not in text


def test_health_checks_and_scrapes_do_not_fill_the_log(client):
    with capture_logs() as lines:
        client.get("/healthz")
        client.get("/metrics", headers={"Authorization": f"Bearer {TOKEN}"})
    assert access_lines(lines()) == []


# ------------------------------------------------------------------ GET /metrics

def test_metrics_need_the_token(client):
    assert client.get("/metrics").status_code == 401
    wrong = {"Authorization": "Bearer wrong-token-0000000000"}
    assert client.get("/metrics", headers=wrong).status_code == 401
    assert client.get("/metrics", headers={"Authorization": TOKEN}).status_code == 401  # no "Bearer"
    r = client.get("/metrics", headers={"Authorization": f"Bearer {TOKEN}"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/plain")
    assert "certivo_http_requests_total" in r.text and "certivo_build_info" in r.text
    assert r.headers["Cache-Control"] == "no-store"  # the usual security headers still apply


def test_a_failed_metrics_login_is_counted_but_the_wrong_token_is_never_logged(client):
    before = sample("certivo_auth_failures_total", reason="metrics_token")
    with capture_logs() as lines:
        client.get("/metrics", headers={"Authorization": "Bearer guessed-token-123456789"})
    assert sample("certivo_auth_failures_total", reason="metrics_token") == before + 1
    assert "guessed-token" not in str(lines())


def test_outside_dev_metrics_are_not_served_without_a_token():
    app = make_mini_app(env="staging")
    with capture_logs(logging.WARNING) as lines:
        app = make_mini_app(env="staging")
    assert TestClient(app).get("/metrics").status_code == 404
    assert any("NOT served" in e["msg"] for e in lines())


def test_in_dev_metrics_work_without_a_token():
    assert TestClient(make_mini_app(env="dev")).get("/metrics").status_code == 200


def test_metrics_can_be_switched_off():
    app = make_mini_app(env="dev", metrics_enabled=False)
    assert TestClient(app).get("/metrics").status_code == 404


def test_a_short_metrics_token_is_refused_at_startup():
    with pytest.raises(ValueError, match="16 characters"):
        make_mini_app(env="staging", metrics_token="short")


# ------------------------------------------------------------------ packet metrics helpers

def test_packet_lag_is_recorded_in_seconds_and_never_negative():
    count = lambda: sample("certivo_packet_ingest_lag_seconds_count", via="live")  # noqa: E731
    total = lambda: sample("certivo_packet_ingest_lag_seconds_sum", via="live")  # noqa: E731
    c0, t0 = count(), total()
    metrics.record_packet("live", 2_500)
    metrics.record_packet("live", -4_000)  # a device clock slightly ahead of ours: zero lag, not negative
    assert count() == c0 + 2
    assert total() == pytest.approx(t0 + 2.5)


def test_duplicates_are_counted_but_add_no_lag_sample():
    c0 = sample("certivo_packet_ingest_lag_seconds_count", via="live")
    d0 = sample("certivo_packets_total", via="live", result="duplicate")
    metrics.record_packet("live", 9_000, duplicate=True)
    assert sample("certivo_packet_ingest_lag_seconds_count", via="live") == c0
    assert sample("certivo_packets_total", via="live", result="duplicate") == d0 + 1


def test_rejections_are_counted_by_code():
    r0 = sample("certivo_packets_total", via="batch", result="rejected")
    c0 = sample("certivo_packets_rejected_total", via="batch", code="seq_conflict")
    metrics.record_rejection("batch", "seq_conflict")
    assert sample("certivo_packets_total", via="batch", result="rejected") == r0 + 1
    assert sample("certivo_packets_rejected_total", via="batch", code="seq_conflict") == c0 + 1
