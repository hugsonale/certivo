from sqlalchemy import select

from app.attestation import verify_attestation
from app.models import CoverageGap, WebhookOutbox
from app.sandbox import make_signed_packet
from tests.conftest import T0


def post_event(client, session, sdk, device, seq, conf, participant="alice", start=None, end=None):
    key, dev_id = device
    start = start if start is not None else T0 - 60_000 + seq * 1000
    end = end if end is not None else start + 1000
    pkt = make_signed_packet(key, session["id"], dev_id, participant, seq, start, end, conf,
                             ["consistent_motion"])
    return client.post(f"/internal/v1/sessions/continuous/{session['id']}/score-events",
                       json=pkt, headers=sdk), pkt


def test_start_requires_api_key(client):
    r = client.post("/v1/sessions/continuous", json={"use_case": "default_video_call"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "missing_api_key"
    r = client.post("/v1/sessions/continuous", json={"use_case": "default_video_call"},
                    headers={"Authorization": "Bearer nope"})
    assert r.json()["error"]["code"] == "invalid_api_key"


def test_start_session_ok_and_errors(client, auth):
    r = client.post("/v1/sessions/continuous", headers=auth, json={"use_case": "default_video_call"})
    body = r.json()
    assert r.status_code == 201 and body["status"] == "active"
    assert body["re_evaluation_interval_ms"] == 1000 and body["sdk_token"].startswith("skt_")
    r = client.post("/v1/sessions/continuous", headers=auth, json={"use_case": "no_such_policy"})
    assert r.status_code == 404 and r.json()["error"]["code"] == "policy_not_found"
    for bad in (0, -1, "2", 1.5):
        r = client.post("/v1/sessions/continuous", headers=auth,
                        json={"use_case": "default_video_call", "participant_count": bad})
        assert r.status_code == 422, bad


def test_full_flow_with_drop_and_attestation(client, auth, app, device, session):
    sess, sdk = session
    outcomes = []
    for seq, conf in enumerate([930, 920, 150, 140, 900]):
        r, _ = post_event(client, sess, sdk, device, seq, conf)
        assert r.status_code == 200, r.text
        outcomes.append(r.json()["current_policy_outcome"])
    assert outcomes == ["accept", "accept", "fallback", "reject", "accept"]

    with app.state.session_factory() as db:
        events = list(db.scalars(select(WebhookOutbox)))
    assert [e.event_type for e in events] == ["session.confidence_dropped"]
    assert events[0].payload["seq"] == 3

    st = client.get(f"/v1/sessions/continuous/{sess['id']}/status", headers=auth).json()
    assert st["session_status"] == "active"
    assert st["participants"][0]["confidence_milli"] == 900
    assert st["participants"][0]["events_accepted"] == 5

    end = client.post(f"/v1/sessions/continuous/{sess['id']}/end", headers=auth)
    assert end.status_code == 200
    att = end.json()["attestation"]
    p = att["payload"]["participants"][0]
    assert (p["events_accepted"], p["min_confidence_milli"], p["reject_transitions"]) == (5, 140, 1)
    assert p["missed_intervals"] == 0 and p["final_outcome"] == "accept"
    assert end.json()["coverage_summary"]["coverage_milli"] == 1000

    pub = client.get("/.well-known/certivo-keys").json()["keys"][0]
    assert pub["key_id"] == att["key_id"] == "att-test-1"
    assert verify_attestation(att, pub["public_key"])
    att["payload"]["participants"][0]["min_confidence_milli"] = 999  # tamper
    assert not verify_attestation(att, pub["public_key"])


def test_end_is_idempotent(client, auth, session):
    sess, _ = session
    a = client.post(f"/v1/sessions/continuous/{sess['id']}/end", headers=auth).json()
    b = client.post(f"/v1/sessions/continuous/{sess['id']}/end", headers=auth).json()
    assert a["attestation"] == b["attestation"]


def test_duplicate_and_conflicting_seq(client, device, session):
    sess, sdk = session
    r1, pkt = post_event(client, sess, sdk, device, 0, 900)
    assert r1.json()["duplicate"] is False
    again = client.post(f"/internal/v1/sessions/continuous/{sess['id']}/score-events",
                        json=pkt, headers=sdk)
    assert again.status_code == 200 and again.json()["duplicate"] is True
    r2, _ = post_event(client, sess, sdk, device, 0, 100)  # same seq, different content
    assert r2.status_code == 409 and r2.json()["error"]["code"] == "seq_conflict"


def test_out_of_order_and_monotonic(client, device, session):
    sess, sdk = session
    assert post_event(client, sess, sdk, device, 5, 900)[0].status_code == 200
    r, _ = post_event(client, sess, sdk, device, 4, 900)
    assert r.status_code == 409 and r.json()["error"]["code"] == "seq_out_of_order"
    r, _ = post_event(client, sess, sdk, device, 6, 900, start=T0 - 200_000, end=T0 - 199_000)
    assert r.status_code == 409 and r.json()["error"]["code"] == "non_monotonic_interval"


def test_bad_signature_and_unknown_device(client, device, session):
    sess, sdk = session
    r, pkt = post_event(client, sess, sdk, device, 0, 900)
    pkt["seq"], pkt["confidence_milli"] = 1, 999  # tamper after signing
    r = client.post(f"/internal/v1/sessions/continuous/{sess['id']}/score-events",
                    json=pkt, headers=sdk)
    assert r.status_code == 401 and r.json()["error"]["code"] == "invalid_device_signature"
    pkt["device_id"] = "dev_" + "0" * 32
    r = client.post(f"/internal/v1/sessions/continuous/{sess['id']}/score-events",
                    json=pkt, headers=sdk)
    assert r.status_code == 401


def test_packet_bound_to_its_session(client, auth, device, session):
    sess, sdk = session
    other = client.post("/v1/sessions/continuous", headers=auth,
                        json={"use_case": "default_video_call"}).json()
    key, dev_id = device
    pkt = make_signed_packet(key, other["id"], dev_id, "alice", 0, T0 - 2000, T0 - 1000, 900)
    r = client.post(f"/internal/v1/sessions/continuous/{sess['id']}/score-events",
                    json=pkt, headers=sdk)  # signed for another session -> replay rejected
    assert r.status_code == 401


def test_token_checks(client, session):
    sess, sdk = session
    url = f"/internal/v1/sessions/continuous/{sess['id']}/pause"
    assert client.post(url).status_code == 401
    assert client.post(url, headers={"Authorization": "Bearer skt_wrong"}).status_code == 401
    assert client.post(url, headers=sdk).status_code == 204


def test_validation_errors(client, device, session):
    sess, sdk = session
    key, dev_id = device
    pkt = make_signed_packet(key, sess["id"], dev_id, "alice", 0, T0 - 2000, T0 - 1000, 900)
    for field, value in [("confidence_milli", 0.9), ("confidence_milli", 1001), ("seq", -1),
                         ("v", 2), ("explanation", {"reason_codes": []})]:
        bad = dict(pkt, **{field: value})
        r = client.post(f"/internal/v1/sessions/continuous/{sess['id']}/score-events",
                        json=bad, headers=sdk)
        assert r.status_code == 422, field
        assert r.json()["error"]["code"] == "validation_error"


def test_future_timestamp_and_bad_interval(client, device, session):
    sess, sdk = session
    r, _ = post_event(client, sess, sdk, device, 0, 900, start=T0 + 120_000, end=T0 + 121_000)
    assert r.status_code == 422 and r.json()["error"]["code"] == "timestamp_in_future"
    r, _ = post_event(client, sess, sdk, device, 1, 900, start=T0 - 1000, end=T0 - 1000)
    assert r.json()["error"]["code"] == "invalid_interval"


def test_event_after_end_is_409(client, auth, device, session):
    sess, sdk = session
    client.post(f"/v1/sessions/continuous/{sess['id']}/end", headers=auth)
    r, _ = post_event(client, sess, sdk, device, 0, 900)
    assert r.status_code == 409 and r.json()["error"]["code"] == "session_not_active"


def test_partner_isolation(client, other_auth, device, session):
    sess, _ = session
    assert client.get(f"/v1/sessions/continuous/{sess['id']}/status",
                      headers=other_auth).status_code == 404
    assert client.post(f"/v1/sessions/continuous/{sess['id']}/end",
                       headers=other_auth).status_code == 404
    assert client.get(f"/v1/devices/{device[1]}", headers=other_auth).status_code == 404


def test_pause_resume_and_coverage_gap(client, auth, app, clock, device, session):
    sess, sdk = session
    base = f"/internal/v1/sessions/continuous/{sess['id']}"
    assert post_event(client, sess, sdk, device, 0, 900)[0].status_code == 200
    clock.t += 10_000
    assert client.post(f"{base}/pause", json={"reason": "connectivity"}, headers=sdk).status_code == 204
    assert client.get(f"/v1/sessions/continuous/{sess['id']}/status",
                      headers=auth).json()["session_status"] == "paused"
    clock.t += 20_000
    # a valid packet implicitly resumes and closes the gap
    assert post_event(client, sess, sdk, device, 3, 900, start=T0 - 5000, end=T0 - 4000)[0].status_code == 200
    clock.t += 10_000
    end = client.post(f"/v1/sessions/continuous/{sess['id']}/end", headers=auth).json()
    cov = end["coverage_summary"]
    assert cov["gap_count"] == 1 and cov["paused_ms"] == 20_000
    assert cov["gaps"][0]["reason"] == "connectivity"
    assert cov["coverage_milli"] == 1000 - 20_000 * 1000 // 40_000  # 500
    assert end["attestation"]["payload"]["participants"][0]["missed_intervals"] == 2
    with app.state.session_factory() as db:
        assert db.scalar(select(CoverageGap)).end_ms is not None
        types = [e.event_type for e in db.scalars(select(WebhookOutbox))]
    assert types == ["session.paused"]


def test_device_registration(client, auth):
    r = client.post("/v1/devices", json={"public_key": "A" * 43}, headers=auth)
    assert r.status_code == 201 and r.json()["trust_tier"] == "software_only"
    r = client.post("/v1/devices", json={"public_key": "short"}, headers=auth)
    assert r.status_code == 422


def test_request_id_header_and_healthz(client):
    r = client.get("/healthz")
    assert r.json() == {"status": "ok"} and r.headers["x-request-id"].startswith("req_")
