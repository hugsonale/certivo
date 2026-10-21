"""P0-12: implausible-pattern detection.

Each pattern is tested as a pure calculation (including the edges where it must NOT fire), then end to
end: a genuine session raises nothing, replayed and forged patterns raise flags, and no flag can ever
change a decision, reject a packet or reach the partner.
"""
import logging
import random
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app import anomaly
from app.anomaly import DEFAULTS, detect
from app.models import ScoreEvent, SecurityFlag, WebhookOutbox
from app.sandbox import make_signed_packet, run_simulation
from tests.conftest import T0

N = DEFAULTS.window  # 30


# --------------------------------------------------------------------------------------- helpers


def rows(confs, *, gaps=None, via="live", claimed=1000, first_seq=0, seqs=None):
    """A participant's latest scores, oldest first. `gaps` are the milliseconds between arrivals."""
    gaps = gaps if gaps is not None else [1000 + (i * 7) % 23 for i in range(len(confs) - 1)]  # jittery
    arrival = T0
    out = []
    for i, conf in enumerate(confs):
        if i:
            arrival += gaps[i - 1]
        seq = seqs[i] if seqs else first_seq + i
        out.append(SimpleNamespace(seq=seq, confidence_milli=conf, interval_start_ms=T0 + i * claimed,
                                   interval_end_ms=T0 + (i + 1) * claimed, received_at_ms=arrival,
                                   received_via=via))
    return out


def varied(n=N, seed=1):
    rng = random.Random(seed)
    return [rng.randint(850, 960) for _ in range(n)]


def kinds(found):
    return {kind for kind, _ in found}


# ---------------------------------------------------------- pattern: flat maximum confidence


def test_a_flat_maximum_confidence_for_the_whole_window_is_flagged():
    found = dict(detect(rows([1000] * N)))
    assert found["flat_maximum_confidence"] == {"intervals": N, "min_milli": 1000, "max_milli": 1000}


@pytest.mark.parametrize("confs,flagged", [
    ([995, 1000] * (N // 2), True),            # spread 5, all at or above 990: still flat
    ([994, 1000] * (N // 2), False),           # spread 6: some natural variation
    ([990] * N, True),                          # exactly on the line
    ([989] * N, False),                         # one below the line: not "maximum"
    ([1000] * (N - 1), False),                  # too few intervals to judge
    ([1000] * (N - 1) + [900], False),          # one low interval is enough variation
    ([930] * N, False),                         # constant but not maximum (what the sandbox demo sends)
])
def test_flat_maximum_edges(confs, flagged):
    assert ("flat_maximum_confidence" in kinds(detect(rows(confs)))) is flagged


# ----------------------------------------------------------- pattern: impossible score jumps


def test_repeated_enormous_swings_are_flagged_but_one_swing_is_not():
    flapping = [1000, 50] + varied(N - 2)
    flapping[10], flapping[11], flapping[20], flapping[21] = 960, 40, 950, 20  # more swings
    assert "impossible_score_jumps" in kinds(detect(rows(flapping)))
    one_swing = varied()  # a person covering the camera once: 900 -> 100 -> back
    one_swing[10], one_swing[11], one_swing[12] = 950, 40, 900
    assert "impossible_score_jumps" not in kinds(detect(rows(one_swing)))


@pytest.mark.parametrize("dips,size,flagged", [
    (1, 910, False),   # one dip is a person covering the camera and uncovering it: two jumps, not enough
    (2, 910, True),    # two dips are four jumps
    (2, 900, True),    # exactly on the line counts
    (2, 899, False),   # one milli short of the line does not
    (5, 950, True),
])
def test_jump_edges(dips, size, flagged):
    confs = [950] * N
    for k in range(dips):  # each dip drops by `size` for one interval, then recovers: two jumps of `size`
        confs[5 + k * 5] = 950 - size
    assert ("impossible_score_jumps" in kinds(detect(rows(confs)))) is flagged


# ------------------------------------------------------------- patterns: timing (live only)


def test_packets_arriving_far_faster_than_the_time_they_claim_look_like_a_replay():
    blast = rows(varied(), gaps=[40 + (i % 5) for i in range(N - 1)])  # 1 second claimed, ~40 ms apart
    found = dict(detect(blast))
    assert "faster_than_real_time" in found
    assert found["faster_than_real_time"]["claimed_ms"] == 29_000 and found["faster_than_real_time"]["arrival_span_ms"] < 2_000


@pytest.mark.parametrize("gap,flagged", [(240, True), (260, False), (1000, False)])
def test_fast_edges(gap, flagged):
    jittered = [gap + (i % 9) - 4 for i in range(N - 1)]
    assert ("faster_than_real_time" in kinds(detect(rows(varied(), gaps=jittered)))) is flagged


@pytest.mark.parametrize("wobble,flagged", [(0, True), (1, True), (2, False), (30, False)])
def test_zero_jitter_edges(wobble, flagged):
    gaps = [1000 + (wobble if i % 2 else 0) for i in range(N - 1)]  # alternates between 1000 and 1000+wobble
    assert ("zero_timing_jitter" in kinds(detect(rows(varied(), gaps=gaps)))) is flagged


def test_timing_is_never_judged_on_packets_uploaded_in_a_batch():
    burst = rows(varied(), gaps=[0] * (N - 1), via="batch")  # an outage upload arrives all at once, legitimately
    assert kinds(detect(burst)) == set()
    mixed = rows(varied(), gaps=[0] * (N - 1))
    mixed[5].received_via = "batch"
    assert kinds(detect(mixed)) == set()
    assert "flat_maximum_confidence" in kinds(detect(rows([1000] * N, via="batch")))  # content still counts


def test_a_missing_packet_inside_the_window_hides_the_timing_evidence():
    seqs = list(range(15)) + list(range(16, 16 + N - 15))  # seq 15 never arrived
    blast = rows(varied(), gaps=[5] * (N - 1), seqs=seqs)
    assert kinds(detect(blast)) == set()


def test_fewer_than_a_window_of_scores_is_never_judged():
    assert detect(rows([1000] * (N - 1), gaps=[5] * (N - 2))) == [] and detect([]) == []


@pytest.mark.parametrize("seed", range(1, 41))
def test_genuine_looking_sessions_never_raise_flags(seed):
    rng = random.Random(seed)
    confs = [rng.randint(780, 975) for _ in range(N)]
    gaps = [1000 + rng.randint(-45, 70) for _ in range(N - 1)]
    assert detect(rows(confs, gaps=gaps)) == []


# ------------------------------------------------------------------- end to end, through the API


def send(client, sess, sdk, device, seq, conf, participant="alice", model="sandbox-0"):
    key, dev_id = device
    start = T0 + seq * 1000
    pkt = make_signed_packet(key, sess["id"], dev_id, participant, seq, start, start + 1000, conf,
                             ["consistent_motion"], model_version=model)
    r = client.post(f"/internal/v1/sessions/continuous/{sess['id']}/score-events", json=pkt, headers=sdk)
    assert r.status_code == 200, r.text
    return r


def play(client, clock, sess, sdk, device, confs, arrivals, participant="alice"):
    for seq, (conf, at) in enumerate(zip(confs, arrivals, strict=True)):
        clock.t = at
        send(client, sess, sdk, device, seq, conf, participant)


def paced(n, seed=3):
    """Arrival times of a real device: one packet per second, each a little late by a varying amount."""
    rng = random.Random(seed)
    return [T0 + (i + 1) * 1000 + rng.randint(0, 90) for i in range(n)]


def flags_of(app):
    with app.state.session_factory() as db:
        return [(f.participant_ref, f.flag_type) for f in db.scalars(select(SecurityFlag).order_by(SecurityFlag.id))]


def test_a_genuine_session_raises_no_flags(client, app, device, session, clock):
    sess, sdk = session
    play(client, clock, sess, sdk, device, varied(60, seed=5), paced(60))
    assert flags_of(app) == []


def test_the_sandbox_simulation_raises_no_flags(client, app, partner_key):
    out = run_simulation(client, partner_key[1], now_ms=T0)
    assert out["attestation_verified"] is True
    assert flags_of(app) == []


def test_a_replay_arriving_faster_than_real_time_is_flagged_once(client, app, device, session, clock):
    sess, sdk = session
    confs = varied(50, seed=9)
    play(client, clock, sess, sdk, device, confs, [T0 + 60_000 + i * 50 for i in range(50)])
    assert flags_of(app) == [("alice", "faster_than_real_time"), ("alice", "zero_timing_jitter")]
    with app.state.session_factory() as db:
        fast = db.scalar(select(SecurityFlag).where(SecurityFlag.flag_type == "faster_than_real_time"))
    assert (fast.first_seq, fast.last_seq) == (0, 29)  # raised the first time the window was full
    assert fast.detail["claimed_ms"] == 29_000 and fast.partner_id and fast.device_id and fast.raised_at_ms


def test_a_forged_flat_maximum_is_flagged_and_only_for_that_participant(client, app, device, session, clock):
    sess, sdk = session
    arrivals = paced(40)
    for seq in range(40):
        clock.t = arrivals[seq]
        send(client, sess, sdk, device, seq, 1000, participant="mallory")
        send(client, sess, sdk, device, seq, 860 + (seq * 37) % 90, participant="alice")
    assert flags_of(app) == [("mallory", "flat_maximum_confidence")]


def test_forged_flapping_scores_are_flagged(client, app, device, session, clock):
    sess, sdk = session
    play(client, clock, sess, sdk, device, [1000, 40] * 20, paced(40))
    assert ("alice", "impossible_score_jumps") in flags_of(app)


def test_a_scripted_sender_with_perfectly_even_timing_is_flagged(client, app, device, session, clock):
    sess, sdk = session
    play(client, clock, sess, sdk, device, varied(40, seed=2), [T0 + (i + 1) * 1000 for i in range(40)])
    assert flags_of(app) == [("alice", "zero_timing_jitter")]


# ---------------------------------------------------------------- flag only, never block


def test_flags_never_change_a_decision_reject_a_packet_or_reach_the_partner(
        client, auth, app, device, session, clock):
    sess, sdk = session
    play(client, clock, sess, sdk, device, [1000] * 45, paced(45))  # flagged as a flat maximum
    assert ("alice", "flat_maximum_confidence") in flags_of(app)
    with app.state.session_factory() as db:
        events = list(db.scalars(select(ScoreEvent).where(ScoreEvent.session_id == sess["id"])))
        assert len(events) == 45 and {e.outcome for e in events} == {"accept"}  # all stored, all judged on merit
        assert db.scalar(select(WebhookOutbox)) is None
    status = client.get(f"/v1/sessions/continuous/{sess['id']}/status", headers=auth).json()
    ended = client.post(f"/v1/sessions/continuous/{sess['id']}/end", headers=auth).json()
    assert "flag" not in str(status).lower() and "flag" not in str(ended).lower()  # internal signals only
    assert ended["attestation"]["payload"]["participants"][0]["events_accepted"] == 45


def test_a_failure_inside_detection_can_never_reject_an_upload(client, app, device, session, clock,
                                                              monkeypatch, caplog):
    def broken(*args, **kwargs):
        raise RuntimeError("detector bug")

    monkeypatch.setattr(anomaly, "detect", broken)
    sess, sdk = session
    with caplog.at_level(logging.ERROR, logger="certivo.sessions"):
        play(client, clock, sess, sdk, device, varied(35), paced(35))  # every one still answers 200
    assert "the upload itself is unaffected" in caplog.text
    with app.state.session_factory() as db:
        assert len(list(db.scalars(select(ScoreEvent)))) == 35  # nothing was lost
    assert flags_of(app) == []


def test_detection_can_be_switched_off(client, app, device, session, clock):
    app.state.settings.anomaly_detection_enabled = False
    sess, sdk = session
    play(client, clock, sess, sdk, device, [1000] * 40, paced(40))
    assert flags_of(app) == []


# ------------------------------------------------------------------------ the batch path


def batch(client, sess, sdk, device, confs, first_seq=0):
    key, dev_id = device
    packets = [make_signed_packet(key, sess["id"], dev_id, "alice", first_seq + i, T0 + (first_seq + i) * 1000,
                                  T0 + (first_seq + i) * 1000 + 1000, c, ["a"]) for i, c in enumerate(confs)]
    r = client.post(f"/internal/v1/sessions/continuous/{sess['id']}/score-events/batch",
                    json={"packets": packets}, headers=sdk)
    assert r.status_code == 200, r.text


def test_a_genuine_outage_upload_arrives_in_a_burst_and_raises_nothing(client, app, device, session, clock):
    sess, sdk = session
    clock.t = T0 + 90_000  # the backend was unreachable for 90 seconds, then everything is sent at once
    confs = varied(50, seed=11)
    batch(client, sess, sdk, device, confs[:25])
    batch(client, sess, sdk, device, confs[25:], first_seq=25)
    assert flags_of(app) == []
    with app.state.session_factory() as db:
        assert {e.received_via for e in db.scalars(select(ScoreEvent))} == {"batch"}


def test_content_patterns_are_still_caught_in_an_uploaded_batch(client, app, device, session, clock):
    sess, sdk = session
    clock.t = T0 + 90_000
    batch(client, sess, sdk, device, [1000] * 25)
    batch(client, sess, sdk, device, [1000] * 15, first_seq=25)
    assert flags_of(app) == [("alice", "flat_maximum_confidence")]


def test_live_packets_are_recorded_as_live(client, app, device, session, clock):
    sess, sdk = session
    clock.t = T0 + 2000
    send(client, sess, sdk, device, 0, 900)
    with app.state.session_factory() as db:
        assert db.scalar(select(ScoreEvent.received_via)) == "live"
