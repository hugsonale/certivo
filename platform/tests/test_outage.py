"""P0-08: outage tolerance. The backend is unreachable for a while, the SDK keeps scoring and
buffers signed packets, and on reconnection uploads them in order. The attestation must disclose
the gap rather than present the session as continuously verified (System Design Document 7.1).

The real SDK does not exist yet (P0-25), so `BufferingSdk` below is a small stand-in that behaves
the way the SDK is specified to behave.
"""
from sqlalchemy import select

from app.attestation import verify_attestation
from app.crypto import SCORE_DOMAIN, sign_message
from app.models import CoverageGap, ScoreEvent, WebhookOutbox
from app.sandbox import make_signed_packet
from app.schemas import MAX_BATCH_PACKETS
from app.services.sessions import _uncovered_ms
from tests.conftest import T0

THRESHOLD = 10_000  # the default gap_disclosure_threshold_ms


def packet(device, sess, seq, participant="alice", conf=930, base=T0):
    """One signed one-second packet; interval number `seq` starts `seq` seconds after `base`."""
    key, dev_id = device
    start = base + seq * 1000
    return make_signed_packet(key, sess["id"], dev_id, participant, seq, start, start + 1000, conf,
                              ["consistent_motion"])


def single_url(sess):
    return f"/internal/v1/sessions/continuous/{sess['id']}/score-events"


def batch_url(sess):
    return single_url(sess) + "/batch"


class BufferingSdk:
    """Sends each packet live. If the backend cannot be reached it buffers the packet instead of
    failing, then uploads the buffer in order, in batches, once the backend is back."""

    def __init__(self, client, sess, sdk_headers):
        self.client, self.sess, self.headers = client, sess, sdk_headers
        self.backend_up = True
        self.buffer = []
        self.batch_results = []

    def _post(self, url, body):
        if not self.backend_up:
            raise ConnectionError("backend unreachable")
        return self.client.post(url, json=body, headers=self.headers)

    def score(self, pkt):
        """Called once per interval, during the call. Must never raise."""
        try:
            r = self._post(single_url(self.sess), pkt)
            assert r.status_code == 200, r.text
        except ConnectionError:
            self.buffer.append(pkt)

    def flush(self):
        while self.buffer:
            chunk = self.buffer[:MAX_BATCH_PACKETS]
            r = self._post(batch_url(self.sess), {"packets": chunk})
            assert r.status_code == 200, r.text
            self.batch_results.append(r.json())
            del self.buffer[:MAX_BATCH_PACKETS]


def attestation_for(client, auth, sess):
    end = client.post(f"/v1/sessions/continuous/{sess['id']}/end", headers=auth)
    assert end.status_code == 200, end.text
    return end.json()


def test_a_simulated_outage_is_buffered_uploaded_in_order_and_disclosed(
        client, auth, app, device, session, clock):
    sess, sdk_headers = session
    sdk = BufferingSdk(client, sess, sdk_headers)
    call_errors = []

    def one_interval(seq):
        clock.t = T0 + (seq + 1) * 1000 + 100  # the packet reaches us 100 ms after its interval
        try:
            sdk.score(packet(device, sess, seq))
        except Exception as exc:  # the call must never be affected by the backend being down
            call_errors.append(exc)

    for seq in range(10):  # 10 seconds of normal, live verification
        one_interval(seq)
    sdk.backend_up = False
    for seq in range(10, 50):  # 40 seconds with the backend unreachable
        one_interval(seq)
    assert len(sdk.buffer) == 40

    clock.t = T0 + 50_500  # the backend is reachable again
    sdk.backend_up = True
    sdk.flush()
    for seq in range(50, 53):  # and live verification carries on
        one_interval(seq)
    clock.t = T0 + 53_500

    assert call_errors == []  # no call impact: scoring never failed, not once

    # Uploaded in order: the database saw 0, 1, 2 ... 52, none missing, none reordered.
    with app.state.session_factory() as db:
        stored = list(db.scalars(select(ScoreEvent).where(ScoreEvent.session_id == sess["id"])
                                 .order_by(ScoreEvent.id)))
    assert [e.seq for e in stored] == list(range(53))
    assert stored[20].interval_start_ms == T0 + 20_000  # original timestamps were kept

    # 40 buffered packets went up as two batches (25 + 15); only the first added a gap.
    first, second = sdk.batch_results
    assert (first["accepted_count"], first["gaps_recorded"]) == (25, 1)
    assert (second["accepted_count"], second["gaps_recorded"]) == (15, 0)

    result = attestation_for(client, auth, sess)
    coverage = result["coverage_summary"]
    assert coverage["gap_count"] == 1
    assert coverage["gaps"] == [{"start_ms": T0 + 10_000, "end_ms": T0 + 50_500,
                                 "reason": "delayed_upload"}]
    assert coverage["paused_ms"] == 40_500
    duration = 53_500
    assert coverage["coverage_milli"] == (duration - 40_500) * 1000 // duration  # live coverage only
    participant = result["attestation"]["payload"]["participants"][0]
    assert participant["events_accepted"] == 53 and participant["missed_intervals"] == 0

    pub = client.get("/.well-known/certivo-keys").json()["keys"][0]["public_key"]
    assert verify_attestation(result["attestation"], pub)


def test_resending_a_batch_is_safe_and_adds_no_second_gap(client, auth, device, session, clock):
    sess, sdk = session
    clock.t = T0 + 40_000
    body = {"packets": [packet(device, sess, s) for s in range(20)]}
    first = client.post(batch_url(sess), json=body, headers=sdk).json()
    clock.t += 5_000  # the SDK did not see our answer and retries a little later
    again = client.post(batch_url(sess), json=body, headers=sdk).json()
    assert (first["accepted_count"], first["gaps_recorded"]) == (20, 1)
    assert (again["accepted_count"], again["duplicate_count"], again["gaps_recorded"]) == (0, 20, 0)
    assert all(r["accepted"] and r["duplicate"] for r in again["results"])
    assert attestation_for(client, auth, sess)["coverage_summary"]["gap_count"] == 1


def test_a_batch_that_is_not_late_records_no_gap(client, auth, device, session, clock):
    sess, sdk = session
    clock.t = T0 + 5_000  # everything below ended less than 10 seconds ago
    body = {"packets": [packet(device, sess, s) for s in range(4)]}
    r = client.post(batch_url(sess), json=body, headers=sdk).json()
    assert (r["accepted_count"], r["gaps_recorded"]) == (4, 0)
    coverage = attestation_for(client, auth, sess)["coverage_summary"]
    assert coverage["gap_count"] == 0 and coverage["coverage_milli"] == 1000


def test_one_bad_packet_is_reported_and_the_rest_are_kept(client, auth, device, session, clock):
    sess, sdk = session
    clock.t = T0 + 30_000
    packets = [packet(device, sess, s) for s in range(4)]
    packets[1]["confidence_milli"] = 999  # tampered after signing
    r = client.post(batch_url(sess), json={"packets": packets}, headers=sdk)
    assert r.status_code == 200
    body = r.json()
    assert [x["accepted"] for x in body["results"]] == [True, False, True, True]
    assert body["results"][1]["error"]["code"] == "invalid_device_signature"
    assert body["results"][1]["index"] == 1
    assert (body["accepted_count"], body["rejected_count"]) == (3, 1)
    # the rejected packet left no trace, and did not widen the gap
    gap = attestation_for(client, auth, sess)["coverage_summary"]["gaps"][0]
    assert gap["start_ms"] == T0  # seq 0 is the oldest packet that was accepted


def test_packets_out_of_order_inside_a_batch_are_refused(client, device, session, clock):
    sess, sdk = session
    clock.t = T0 + 20_000
    packets = [packet(device, sess, s) for s in (3, 2, 4)]
    body = client.post(batch_url(sess), json={"packets": packets}, headers=sdk).json()
    assert [x["accepted"] for x in body["results"]] == [True, False, True]
    assert body["results"][1]["error"]["code"] == "seq_out_of_order"


def test_a_packet_signed_for_another_session_is_refused(client, auth, device, session, clock):
    sess, sdk = session
    other = client.post("/v1/sessions/continuous", headers=auth,
                        json={"use_case": "default_video_call"}).json()
    clock.t = T0 + 5_000
    packets = [packet(device, sess, 0), packet(device, other, 1)]
    body = client.post(batch_url(sess), json={"packets": packets}, headers=sdk).json()
    assert [x["accepted"] for x in body["results"]] == [True, False]
    assert body["results"][1]["error"]["code"] == "invalid_device_signature"


def test_packets_the_sdk_could_not_keep_are_disclosed_as_missing(client, auth, device, session, clock):
    """The SDK's buffer overflowed: scores for seconds 5 to 24 are gone for good."""
    sess, sdk = session
    clock.t = T0 + 6_000
    live = {"packets": [packet(device, sess, s) for s in range(5)]}
    assert client.post(batch_url(sess), json=live, headers=sdk).json()["gaps_recorded"] == 0

    clock.t = T0 + 40_000
    late = {"packets": [packet(device, sess, s) for s in range(25, 35)]}
    body = client.post(batch_url(sess), json=late, headers=sdk).json()
    assert body["accepted_count"] == 10 and body["gaps_recorded"] == 2

    result = attestation_for(client, auth, sess)
    reasons = {g["reason"]: g for g in result["coverage_summary"]["gaps"]}
    assert reasons["missing_packets"] == {"start_ms": T0 + 5_000, "end_ms": T0 + 25_000,
                                          "reason": "missing_packets"}
    assert reasons["delayed_upload"]["start_ms"] == T0 + 25_000
    assert result["coverage_summary"]["paused_ms"] == 35_000  # touching gaps, counted once
    participant = result["attestation"]["payload"]["participants"][0]
    assert participant["events_accepted"] == 15 and participant["missed_intervals"] == 20


def test_an_explicit_pause_that_covers_the_outage_is_not_counted_twice(
        client, auth, device, session, clock):
    sess, sdk = session
    base = f"/internal/v1/sessions/continuous/{sess['id']}"
    clock.t = T0 + 5_000
    assert client.post(batch_url(sess), json={"packets": [packet(device, sess, s) for s in range(5)]},
                       headers=sdk).status_code == 200
    assert client.post(base + "/pause", json={"reason": "connectivity"}, headers=sdk).status_code == 204
    clock.t = T0 + 45_000
    body = client.post(batch_url(sess), json={"packets": [packet(device, sess, s) for s in range(5, 25)]},
                       headers=sdk).json()
    assert body["accepted_count"] == 20 and body["gaps_recorded"] == 0  # the pause already says it
    coverage = attestation_for(client, auth, sess)["coverage_summary"]
    assert coverage["gap_count"] == 1 and coverage["gaps"][0]["reason"] == "connectivity"


def test_a_late_upload_that_overlaps_a_pause_is_counted_once(client, auth, device, session, clock):
    sess, sdk = session
    base = f"/internal/v1/sessions/continuous/{sess['id']}"
    clock.t = T0 + 5_000
    client.post(batch_url(sess), json={"packets": [packet(device, sess, s) for s in range(5)]}, headers=sdk)
    client.post(base + "/pause", json={"reason": "connectivity"}, headers=sdk)  # gap A starts at 5 s
    clock.t = T0 + 20_000
    assert client.post(base + "/resume", headers=sdk).status_code == 204  # gap A ends at 20 s

    clock.t = T0 + 60_000  # a later outage: packets from 10 s to 31 s arrive only now
    body = client.post(batch_url(sess), json={"packets": [packet(device, sess, s) for s in range(10, 31)]},
                       headers=sdk).json()
    assert body["gaps_recorded"] == 1  # gap B, 10 s to 60 s, overlaps gap A between 10 s and 20 s

    coverage = attestation_for(client, auth, sess)["coverage_summary"]
    assert coverage["gap_count"] == 2
    assert coverage["paused_ms"] == 55_000  # 5 s to 60 s once, not 15 s + 50 s = 65 s
    assert coverage["coverage_milli"] == 5_000 * 1000 // 60_000


def test_overlapping_gaps_are_counted_once():
    def gap(start, end):
        return CoverageGap(session_id="cs_x", start_ms=start, end_ms=end, reason="other")

    assert _uncovered_ms([gap(0, 10), gap(5, 20), gap(30, 40)], 0, 100) == 30
    assert _uncovered_ms([gap(0, 50), gap(10, 20)], 0, 100) == 50  # one inside another
    assert _uncovered_ms([gap(90, None)], 0, 100) == 10  # an open gap runs to now
    assert _uncovered_ms([gap(-50, 10)], 0, 100) == 10  # only time inside the session counts
    assert _uncovered_ms([], 0, 100) == 0


def test_a_confidence_drop_in_buffered_packets_is_reported_with_its_original_time(
        client, app, device, session, clock):
    sess, sdk = session
    clock.t = T0 + 60_000
    packets = [packet(device, sess, s, conf=c) for s, c in enumerate([930, 920, 150, 140, 900])]
    body = client.post(batch_url(sess), json={"packets": packets}, headers=sdk).json()
    assert [r["current_policy_outcome"] for r in body["results"]] == [
        "accept", "accept", "fallback", "reject", "accept"]
    with app.state.session_factory() as db:
        events = list(db.scalars(select(WebhookOutbox)))
    assert [e.event_type for e in events] == ["session.confidence_dropped"]
    assert events[0].payload["seq"] == 3
    assert events[0].payload["occurred_at_ms"] == T0 + 4_000  # when it happened, not when we heard


def test_the_largest_allowed_batch_fits_the_request_size_limit(client, device, session, clock):
    """Maximum-size packets: longest names, every reason code and signal used."""
    sess, sdk = session
    key, dev_id = device
    clock.t = T0 + 120_000
    packets = []
    for seq in range(MAX_BATCH_PACKETS):
        body = {
            "v": 1, "participant_reference": "p" * 64, "device_id": dev_id, "seq": seq,
            "interval_start_ms": T0 + seq * 1000, "interval_end_ms": T0 + seq * 1000 + 1000,
            "confidence_milli": 900, "model_version": "m" * 64,
            "explanation": {"reason_codes": [f"reason_{i}".ljust(48, "x") for i in range(8)],
                            "signal_milli": {f"signal_{i}".ljust(48, "x"): 1000 for i in range(16)}},
        }
        body["device_signature"] = sign_message(key, SCORE_DOMAIN, dict(body, session_id=sess["id"]))
        packets.append(body)
    r = client.post(batch_url(sess), json={"packets": packets}, headers=sdk)
    assert r.status_code == 200, r.text
    assert r.json()["accepted_count"] == MAX_BATCH_PACKETS


def test_batch_requests_are_checked_like_every_sdk_request(client, auth, device, session):
    sess, sdk = session
    one = [packet(device, sess, 0)]
    assert client.post(batch_url(sess), json={"packets": one}).status_code == 401
    r = client.post(batch_url(sess), json={"packets": one}, headers={"Authorization": "Bearer skt_wrong"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "invalid_session_token"

    for bad in ({"packets": []},
                {"packets": [packet(device, sess, s) for s in range(MAX_BATCH_PACKETS + 1)]},
                {"packets": one, "extra": 1},
                {}):
        r = client.post(batch_url(sess), json=bad, headers=sdk)
        assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"

    client.post(f"/v1/sessions/continuous/{sess['id']}/end", headers=auth)
    r = client.post(batch_url(sess), json={"packets": one}, headers=sdk)
    assert r.status_code == 409 and r.json()["error"]["code"] == "session_not_active"
