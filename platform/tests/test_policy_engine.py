"""P0-11: policy engine v1.

Unit tests for each rule (they are pure calculations), then the same rules end to end through the API,
including the guarantee that changing a policy never alters a call that is already in progress.
"""
import copy

import pytest
from sqlalchemy import select

from app.admin import create_api_key
from app.attestation import config_sha256
from app.models import Policy, ScoreEvent, WebhookOutbox
from app.policy import (
    DEFAULT_POLICY_CONFIG,
    build_config,
    effective_confidence,
    evaluate,
    is_model_supported,
    normalize_config,
    outcome_to_report,
    validate_policy_settings,
)
from app.sandbox import make_signed_packet
from tests.conftest import T0

CFG = DEFAULT_POLICY_CONFIG  # accept at 700, reject below 400, two lows in a row


def cfg(**changes):
    return normalize_config({**copy.deepcopy(CFG), **changes})


# ------------------------------------------------------------------ rule: thresholds and bands


def test_a_confidence_at_or_above_the_accept_line_is_accepted():
    assert evaluate(CFG, [], 700) == "accept" and evaluate(CFG, [], 1000) == "accept"


def test_a_confidence_between_the_lines_is_a_fallback():
    assert evaluate(CFG, [], 699) == "fallback" and evaluate(CFG, [], 400) == "fallback"


def test_one_low_interval_is_only_a_fallback_and_the_second_in_a_row_is_a_reject():
    assert evaluate(CFG, [], 399) == "fallback"
    assert evaluate(CFG, [399], 150) == "reject"


def test_a_good_interval_ends_a_run_of_low_ones_immediately():
    assert evaluate(CFG, [150, 900], 150) == "fallback"  # the 900 broke the run, so this is the first low
    assert evaluate(CFG, [150, 500], 150) == "fallback"  # a borderline interval also ends the run


def test_drop_consecutive_sets_how_many_lows_make_a_reject():
    three = cfg(drop_consecutive=3)
    assert [evaluate(three, [], 100), evaluate(three, [100], 100), evaluate(three, [100, 100], 100)] == [
        "fallback", "fallback", "reject"]
    one = cfg(drop_consecutive=1)
    assert evaluate(one, [], 100) == "reject"


def test_a_partner_can_move_the_lines():
    strict = cfg(accept_min_milli=900, reject_below_milli=600)
    assert evaluate(strict, [], 850) == "fallback" and evaluate(strict, [], 950) == "accept"
    assert evaluate(strict, [500], 500) == "reject"


def test_the_same_inputs_always_give_the_same_answer():
    runs = {evaluate(CFG, [120, 340], 90) for _ in range(50)}
    assert runs == {"reject"}


# --------------------------------------------------------- rule: weighting by device trust tier


def test_the_tier_penalty_is_subtracted_by_the_devices_trust_tier():
    config = cfg(tier_penalty_milli={"hardware_attested": 0, "platform_authenticated": 100, "software_only": 250})
    assert effective_confidence(config, "hardware_attested", "m", 800) == 800
    assert effective_confidence(config, "platform_authenticated", "m", 800) == 700
    assert effective_confidence(config, "software_only", "m", 800) == 550


def test_an_unrecognised_tier_is_treated_as_the_least_trusted_one():
    config = cfg(tier_penalty_milli={"software_only": 250})
    assert effective_confidence(config, "something_odd", "m", 800) == 550


def test_the_default_policy_has_no_tier_penalty_so_effective_equals_reported():
    for tier in ("hardware_attested", "platform_authenticated", "software_only"):
        assert effective_confidence(CFG, tier, "m", 812) == 812


def test_a_tier_penalty_can_turn_an_accept_into_a_fallback():
    config = cfg(tier_penalty_milli={"software_only": 200})
    assert evaluate(config, [], effective_confidence(config, "software_only", "m", 750)) == "fallback"
    assert evaluate(config, [], effective_confidence(config, "hardware_attested", "m", 750)) == "accept"


def test_the_run_of_low_intervals_is_counted_on_effective_confidence():
    config = cfg(tier_penalty_milli={"software_only": 300})
    first = effective_confidence(config, "software_only", "m", 650)   # 350: below the reject line
    second = effective_confidence(config, "software_only", "m", 650)
    assert (first, second) == (350, 350)
    assert evaluate(config, [first], second) == "reject"  # raw 650 would only ever have been a fallback
    assert evaluate(config, [650], 650) == "fallback"


# ---------------------------------------------- rule: score discounting by model version (ML 2.5)


def test_a_model_penalty_applies_only_to_the_listed_version():
    config = cfg(model_penalties=[{"model_version": "edge-1.0", "penalty_milli": 400}])
    assert effective_confidence(config, "software_only", "edge-1.0", 900) == 500
    assert effective_confidence(config, "software_only", "edge-1.1", 900) == 900


def test_tier_and_model_penalties_add_up_and_never_go_below_zero():
    config = cfg(tier_penalty_milli={"software_only": 300},
                 model_penalties=[{"model_version": "edge-1.0", "penalty_milli": 400}])
    assert effective_confidence(config, "software_only", "edge-1.0", 900) == 200
    assert effective_confidence(config, "software_only", "edge-1.0", 500) == 0


def test_a_listed_unsupported_model_version_is_not_supported():
    config = cfg(unsupported_model_versions=["edge-0.9"])
    assert not is_model_supported(config, "edge-0.9") and is_model_supported(config, "edge-1.0")
    assert is_model_supported(CFG, "anything")


def test_a_policy_saved_before_the_new_settings_existed_behaves_exactly_as_before():
    old = {"re_evaluation_interval_ms": 1000, "accept_min_milli": 700, "reject_below_milli": 400,
           "drop_consecutive": 2}
    full = normalize_config(old)
    assert full == CFG
    assert effective_confidence(old, "software_only", "m", 640) == 640
    assert is_model_supported(old, "m")


# ------------------------------------------------------------ rule: the fallback path (FR-C.8)


@pytest.mark.parametrize("previous,outcome,flag,expected", [
    (None, "accept", False, None), ("accept", "accept", True, None),
    # entering reject is always reported, whatever the setting
    ("accept", "reject", False, "reject"), ("fallback", "reject", False, "reject"),
    (None, "reject", False, "reject"), ("accept", "reject", True, "reject"),
    # staying in reject is not a new event
    ("reject", "reject", False, None), ("reject", "reject", True, None),
    # fallback is reported only when the partner asked for it, and only on entering it
    ("accept", "fallback", False, None), ("accept", "fallback", True, "fallback"),
    (None, "fallback", True, "fallback"), ("fallback", "fallback", True, None),
    # coming down from reject to fallback is not a new flag
    ("reject", "fallback", True, None), ("reject", "accept", True, None),
])
def test_what_is_reported_to_the_partner_for_each_change(previous, outcome, flag, expected):
    config = cfg(fallback_behavior="flag_for_review" if flag else "indicator_only")
    assert outcome_to_report(config, previous, outcome) == expected


# ----------------------------------------------------------------------- rule: validation


def settings_problems(settings):
    return {(p["setting"], p["problem"]) for p in validate_policy_settings(settings)}


def test_valid_settings_have_no_problems_and_missing_ones_take_their_defaults():
    assert validate_policy_settings({}) == []
    assert validate_policy_settings({"accept_min_milli": 900, "reject_below_milli": 500}) == []
    assert build_config({"accept_min_milli": 900})["reject_below_milli"] == 400
    assert build_config({"tier_penalty_milli": {"software_only": 50}})["tier_penalty_milli"] == {
        "hardware_attested": 0, "platform_authenticated": 0, "software_only": 50}


def test_unknown_settings_are_refused():
    assert ("hide_rejects", "unknown setting") in settings_problems({"hide_rejects": True})


@pytest.mark.parametrize("settings,setting", [
    ({"accept_min_milli": 1001}, "accept_min_milli"), ({"accept_min_milli": -1}, "accept_min_milli"),
    ({"accept_min_milli": 700.5}, "accept_min_milli"), ({"accept_min_milli": True}, "accept_min_milli"),
    ({"accept_min_milli": "700"}, "accept_min_milli"),
    ({"reject_below_milli": 800}, "reject_below_milli"),  # above the accept line
    ({"drop_consecutive": 0}, "drop_consecutive"),
    ({"re_evaluation_interval_ms": 99}, "re_evaluation_interval_ms"),
    ({"fallback_behavior": "ignore"}, "fallback_behavior"),
    ({"tier_penalty_milli": {"software_only": 1001}}, "tier_penalty_milli"),
    ({"tier_penalty_milli": {"software_only": -1}}, "tier_penalty_milli"),
    ({"tier_penalty_milli": {"gold": 10}}, "tier_penalty_milli"),
    ({"tier_penalty_milli": [1]}, "tier_penalty_milli"),
    ({"model_penalties": [{"model_version": "a", "penalty_milli": 1001}]}, "model_penalties"),
    ({"model_penalties": [{"model_version": "a b", "penalty_milli": 1}]}, "model_penalties"),
    ({"model_penalties": [{"model_version": "a"}]}, "model_penalties"),
    ({"model_penalties": [{"model_version": "a", "penalty_milli": 1}] * 2}, "model_penalties"),
    ({"model_penalties": [{"model_version": f"v{n}", "penalty_milli": 1} for n in range(17)]}, "model_penalties"),
    ({"unsupported_model_versions": ["ok", "ok"]}, "unsupported_model_versions"),
    ({"unsupported_model_versions": [f"v{n}" for n in range(17)]}, "unsupported_model_versions"),
    ({"unsupported_model_versions": ["bad version"]}, "unsupported_model_versions"),
    ({"unsupported_model_versions": "edge"}, "unsupported_model_versions"),
])
def test_each_rule_in_the_spec_refuses_what_it_should(settings, setting):
    assert setting in {name for name, _ in settings_problems(settings)}


def test_every_problem_is_reported_at_once():
    names = {n for n, _ in settings_problems({"accept_min_milli": 5000, "drop_consecutive": 0, "bogus": 1,
                                              "fallback_behavior": "x"})}
    assert names == {"accept_min_milli", "drop_consecutive", "bogus", "fallback_behavior"}
    assert settings_problems("not an object") == {("settings", "must be an object")}


# ------------------------------------------------------------------------------- the API

URL = "/v1/policies"


def make_policy(client, auth, use_case="default_video_call", **settings):
    r = client.post(URL, json={"use_case": use_case, "settings": settings}, headers=auth)
    assert r.status_code == 201, r.text
    return r.json()


def policy_of(app, sess):
    """(policy id, version, settings) that a call copied when it started."""
    from app.models import ContinuousSession
    with app.state.session_factory() as db:
        row = db.get(ContinuousSession, sess["id"])
        return row.policy_id, row.policy_version, row.policy_config


def start(client, auth, use_case="default_video_call"):
    r = client.post("/v1/sessions/continuous", headers=auth, json={"use_case": use_case, "participant_count": 1})
    assert r.status_code == 201, r.text
    body = r.json()
    return body, {"Authorization": f"Bearer {body['sdk_token']}"}


def send(client, sess, sdk, device, seq, confidence, model="sandbox-0", participant="alice"):
    key, dev_id = device
    start_ms = T0 + seq * 1000
    pkt = make_signed_packet(key, sess["id"], dev_id, participant, seq, start_ms, start_ms + 1000,
                             confidence, ["consistent_motion"], model_version=model)
    return client.post(f"/internal/v1/sessions/continuous/{sess['id']}/score-events", json=pkt, headers=sdk)


def outcomes(client, sess, sdk, device, confidences, **kw):
    results = []
    for seq, c in enumerate(confidences):
        r = send(client, sess, sdk, device, seq, c, **kw)
        assert r.status_code == 200, r.text
        results.append(r.json()["current_policy_outcome"])
    return results


def test_a_partner_creates_policy_versions_and_old_ones_never_change(client, auth):
    v1 = make_policy(client, auth, accept_min_milli=800, reject_below_milli=300)
    v2 = make_policy(client, auth, accept_min_milli=900)
    assert (v1["version"], v2["version"]) == (1, 2) and v1["owner"] == "partner"
    assert v1["settings"]["accept_min_milli"] == 800 and v2["settings"]["reject_below_milli"] == 400
    again = client.get(f"{URL}/{v1['id']}", headers=auth).json()
    assert again == v1  # creating version 2 did not touch version 1
    assert v1["settings_sha256"] == config_sha256(v1["settings"]) != v2["settings_sha256"]
    assert make_policy(client, auth, use_case="meetings")["version"] == 1  # versions count per use case


def test_a_bad_policy_is_refused_with_every_problem_listed(client, auth):
    r = client.post(URL, json={"use_case": "default_video_call",
                               "settings": {"accept_min_milli": 5000, "hide_rejects": True}}, headers=auth)
    assert r.status_code == 422 and r.json()["error"]["code"] == "policy_invalid"
    assert {d["setting"] for d in r.json()["error"]["details"]} == {"accept_min_milli", "hide_rejects"}
    assert client.get(URL, headers=auth).json()["data"][0]["owner"] == "certivo"  # nothing was created
    for body in ({"use_case": "Bad Name", "settings": {}}, {"settings": {}},
                 {"use_case": "x", "settings": {}, "extra": 1}):
        assert client.post(URL, json=body, headers=auth).status_code == 422


def test_policies_need_the_right_scope_and_belong_to_one_partner(client, auth, app, partner_key, other_auth):
    partner, _ = partner_key
    assert client.post(URL, json={"use_case": "x", "settings": {}}).status_code == 401
    with app.state.session_factory() as db:
        _, raw = create_api_key(db, partner.id, "read only", ["policies:read"])
        db.commit()
    read_only = {"Authorization": f"Bearer {raw}"}
    denied = client.post(URL, json={"use_case": "x", "settings": {}}, headers=read_only)
    assert denied.status_code == 403 and denied.json()["error"]["code"] == "forbidden_scope"
    assert client.get(URL, headers=read_only).status_code == 200

    mine = make_policy(client, auth, use_case="private_one", accept_min_milli=900)
    assert client.get(f"{URL}/{mine['id']}", headers=other_auth).status_code == 404
    theirs = client.get(URL, headers=other_auth).json()["data"]
    assert [p["owner"] for p in theirs] == ["certivo"]  # they see the built-in default, not mine


def test_the_list_shows_your_policies_and_the_built_in_default_and_pages(client, auth, clock):
    make_policy(client, auth, use_case="a_case")
    clock.t += 1000  # policies are listed newest first, so they need different creation times
    make_policy(client, auth, use_case="a_case", drop_consecutive=3)
    everything = client.get(URL, headers=auth).json()["data"]
    assert [(p["owner"], p["use_case"]) for p in everything].count(("certivo", "default_video_call")) == 1
    assert len([p for p in everything if p["owner"] == "partner"]) == 2
    only = client.get(f"{URL}?use_case=a_case", headers=auth).json()["data"]
    assert [p["version"] for p in only] == [2, 1]  # newest first
    first = client.get(f"{URL}?limit=1", headers=auth).json()
    assert len(first["data"]) == 1 and "next_cursor" in first
    seen = [first["data"][0]["id"]]
    cursor = first["next_cursor"]
    while cursor:
        page = client.get(f"{URL}?limit=1&cursor={cursor}", headers=auth).json()
        seen += [p["id"] for p in page["data"]]
        cursor = page.get("next_cursor")
    assert len(seen) == len(set(seen)) == 3  # every policy once


def test_the_built_in_default_cannot_be_changed_through_the_api(client, auth):
    before = [p for p in client.get(URL, headers=auth).json()["data"] if p["owner"] == "certivo"][0]
    own = make_policy(client, auth, accept_min_milli=950)  # same use case name: a partner policy, not an edit
    after = [p for p in client.get(URL, headers=auth).json()["data"] if p["owner"] == "certivo"][0]
    assert own["owner"] == "partner" and after == before


def test_a_new_call_uses_the_partners_latest_policy_for_the_use_case(client, auth, app):
    make_policy(client, auth, accept_min_milli=800)
    v2 = make_policy(client, auth, accept_min_milli=900)
    sess, _ = start(client, auth)
    policy_id, version, config = policy_of(app, sess)
    assert (policy_id, version, config["accept_min_milli"]) == (v2["id"], 2, 900)


# ---------------------------------------------------------- changing a policy never alters a call


def test_changing_a_policy_never_alters_a_call_in_progress(client, auth, app, device):
    make_policy(client, auth, accept_min_milli=700)  # version 1
    running, sdk = start(client, auth)
    assert policy_of(app, running)[1] == 1
    assert outcomes(client, running, sdk, device, [800]) == ["accept"]

    v2 = make_policy(client, auth, accept_min_milli=950, reject_below_milli=900)  # a much stricter policy
    assert v2["version"] == 2
    assert send(client, running, sdk, device, 1, 800).json()["current_policy_outcome"] == "accept"  # still v1

    with app.state.session_factory() as db:  # even editing the stored row directly does not reach the call
        row = db.scalar(select(Policy).where(Policy.id == policy_of(app, running)[0]))
        row.config = {**row.config, "accept_min_milli": 1000}
        db.commit()
    assert send(client, running, sdk, device, 2, 800).json()["current_policy_outcome"] == "accept"

    fresh, sdk2 = start(client, auth)  # a call that starts after the change gets the new policy
    assert policy_of(app, fresh)[1] == 2
    assert outcomes(client, fresh, sdk2, device, [800]) == ["fallback"]

    ended = client.post(f"/v1/sessions/continuous/{running['id']}/end", headers=auth).json()["attestation"]
    assert ended["payload"]["policy"]["version"] == 1
    assert ended["payload"]["policy"]["config_sha256"] == config_sha256(policy_of(app, running)[2])


# ----------------------------------------------------------------------- rules, end to end


def test_the_tier_penalty_changes_the_decision_and_both_values_are_kept(client, auth, app, device):
    make_policy(client, auth, tier_penalty_milli={"software_only": 300})
    sess, sdk = start(client, auth)
    assert outcomes(client, sess, sdk, device, [800]) == ["fallback"]  # 800 - 300 = 500
    with app.state.session_factory() as db:
        row = db.scalar(select(ScoreEvent).where(ScoreEvent.session_id == sess["id"]))
    assert (row.confidence_milli, row.effective_confidence_milli) == (800, 500)  # the reported value is untouched
    status = client.get(f"/v1/sessions/continuous/{sess['id']}/status", headers=auth).json()
    person = status["participants"][0]
    assert (person["confidence_milli"], person["effective_confidence_milli"]) == (800, 500)


def test_the_run_of_lows_is_counted_on_effective_confidence_end_to_end(client, auth, device):
    make_policy(client, auth, tier_penalty_milli={"software_only": 300})
    sess, sdk = start(client, auth)
    assert outcomes(client, sess, sdk, device, [650, 650]) == ["fallback", "reject"]  # effective 350, 350


def test_a_model_penalty_discounts_only_that_version(client, auth, device):
    make_policy(client, auth, model_penalties=[{"model_version": "edge-1.0", "penalty_milli": 400}])
    sess, sdk = start(client, auth)
    key, dev_id = device
    old = send(client, sess, sdk, device, 0, 900, model="edge-1.0").json()["current_policy_outcome"]
    new = send(client, sess, sdk, device, 1, 900, model="edge-1.1").json()["current_policy_outcome"]
    assert (old, new) == ("fallback", "accept")


def test_scores_from_an_unsupported_model_version_are_refused_and_never_judge_anyone(
        client, auth, app, device):
    make_policy(client, auth, unsupported_model_versions=["edge-0.9"])
    sess, sdk = start(client, auth)
    refused = send(client, sess, sdk, device, 0, 100, model="edge-0.9")
    assert refused.status_code == 422 and refused.json()["error"]["code"] == "model_version_unsupported"
    assert "edge-0.9" in refused.json()["error"]["message"]
    with app.state.session_factory() as db:
        assert db.scalar(select(ScoreEvent)) is None and db.scalar(select(WebhookOutbox)) is None
    assert send(client, sess, sdk, device, 0, 900, model="edge-1.0").json()["current_policy_outcome"] == "accept"
    assert send(client, sess, sdk, device, 1, 100, model="edge-0.9").status_code == 422  # still no effect
    assert send(client, sess, sdk, device, 2, 900, model="edge-1.0").json()["current_policy_outcome"] == "accept"
    record = client.post(f"/v1/sessions/continuous/{sess['id']}/end", headers=auth).json()
    person = record["attestation"]["payload"]["participants"][0]
    assert person["missed_intervals"] == 1 and person["reject_transitions"] == 0  # the refusal is visible


def test_a_refused_model_version_in_a_batch_is_reported_by_position(client, auth, device):
    make_policy(client, auth, unsupported_model_versions=["edge-0.9"])
    sess, sdk = start(client, auth)
    key, dev_id = device
    packets = [make_signed_packet(key, sess["id"], dev_id, "alice", s, T0 + s * 1000, T0 + s * 1000 + 1000, 900,
                                  ["a"], model_version=m) for s, m in enumerate(["edge-1.0", "edge-0.9", "edge-1.0"])]
    body = client.post(f"/internal/v1/sessions/continuous/{sess['id']}/score-events/batch",
                       json={"packets": packets}, headers=sdk).json()
    assert [r["accepted"] for r in body["results"]] == [True, False, True]
    assert body["results"][1]["error"]["code"] == "model_version_unsupported"


def events_of(app):
    with app.state.session_factory() as db:
        return [(e.event_type, e.payload["outcome"], e.payload["seq"]) for e in db.scalars(select(WebhookOutbox))]


def test_a_borderline_result_is_only_an_indicator_by_default(client, auth, app, device):
    sess, sdk = start(client, auth)  # the built-in default: indicator_only
    assert outcomes(client, sess, sdk, device, [900, 500, 520, 900, 300, 200]) == [
        "accept", "fallback", "fallback", "accept", "fallback", "reject"]
    assert events_of(app) == [("session.confidence_dropped", "reject", 5)]  # a reject is always reported


def test_flag_for_review_also_reports_entering_a_borderline_result(client, auth, app, device):
    make_policy(client, auth, fallback_behavior="flag_for_review")
    sess, sdk = start(client, auth)
    assert outcomes(client, sess, sdk, device, [900, 500, 520, 900, 300, 200, 500, 900]) == [
        "accept", "fallback", "fallback", "accept", "fallback", "reject", "fallback", "accept"]
    assert events_of(app) == [
        ("session.confidence_dropped", "fallback", 1),  # accept -> fallback
        ("session.confidence_dropped", "fallback", 4),  # accept -> fallback again
        ("session.confidence_dropped", "reject", 5),  # fallback -> reject
    ]  # staying in fallback (seq 2) and reject -> fallback (seq 6) report nothing


def test_a_first_score_that_is_already_borderline_is_flagged(client, auth, app, device):
    make_policy(client, auth, fallback_behavior="flag_for_review")
    sess, sdk = start(client, auth)
    outcomes(client, sess, sdk, device, [500])
    assert events_of(app) == [("session.confidence_dropped", "fallback", 0)]


def test_no_setting_can_switch_off_the_report_of_a_reject(client, auth, app, device):
    for hidden in ({"fallback_behavior": "indicator_only"}, {"drop_consecutive": 1}):
        make_policy(client, auth, **hidden)
    sess, sdk = start(client, auth)
    outcomes(client, sess, sdk, device, [900, 100])
    assert events_of(app)[-1] == ("session.confidence_dropped", "reject", 1)
    refused = client.post(URL, json={"use_case": "default_video_call", "settings": {"report_rejects": False}},
                          headers=auth)
    assert refused.status_code == 422  # there is no such setting


def test_a_call_whose_policy_predates_the_new_settings_still_works(client, auth, app, device):
    from app.models import ContinuousSession
    sess, sdk = start(client, auth)
    with app.state.session_factory() as db:  # the four settings every call had before P0-11
        row = db.get(ContinuousSession, sess["id"])
        row.policy_config = {"re_evaluation_interval_ms": 1000, "accept_min_milli": 700,
                             "reject_below_milli": 400, "drop_consecutive": 2}
        db.commit()
    assert outcomes(client, sess, sdk, device, [900, 300, 200]) == ["accept", "fallback", "reject"]
