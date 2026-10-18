"""P0-09: daily partitions and retention of the score-events table.

Tests marked "Postgres only" need the real partitioned table; the rest prove the same retention
rules on whichever database the suite runs on (SQLite deletes rows, Postgres drops whole days).
"""
import json

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from app.config import Settings
from app.models import ContinuousSession, ScoreEvent
from app.retention import (
    DAY_MS,
    RetentionNotConfigured,
    create_day_partition,
    day_start_ms,
    drop_expired,
    ensure_partitions,
    is_partitioned,
    list_partitions,
    partition_name,
    run_maintenance,
)
from app.sandbox import make_signed_packet
from tests.conftest import SIGNING_KEY, T0, WEBHOOK_KEY

TODAY = day_start_ms(T0)


def settings(**kw) -> Settings:
    return Settings(database_url="sqlite://", attestation_signing_key=SIGNING_KEY,
                    webhook_secret_key=WEBHOOK_KEY, _env_file=None, **kw)


@pytest.fixture
def postgres_only(db_url):
    if not db_url.startswith("postgresql"):
        pytest.skip("Postgres only")


def make_days_exist(db, days_ago):
    """Postgres: create the daily partitions that history would have created. SQLite: nothing."""
    if not is_partitioned(db):
        return
    have = {low for _, low, _ in list_partitions(db)}
    for d in days_ago:
        if TODAY - d * DAY_MS not in have:
            create_day_partition(db, TODAY - d * DAY_MS)
    db.commit()


def seed(db, partner_id, sid, days_ago, status="ended", events=3):
    """A session that started `days_ago` days ago (an hour into that day) with some score events."""
    started = TODAY - days_ago * DAY_MS + 3_600_000
    db.add(ContinuousSession(
        id=sid, partner_id=partner_id, use_case="u", policy_id="p", policy_version=1, policy_config={},
        status=status, started_at_ms=started, ended_at_ms=started + 1000 if status == "ended" else None,
        sdk_token_hash="t" * 64, sdk_token_expires_at_ms=started + 1))
    db.flush()
    for seq in range(events):
        db.add(ScoreEvent(
            session_id=sid, participant_ref="alice", seq=seq, device_id="dev", interval_start_ms=started,
            interval_end_ms=started + 1000, confidence_milli=900, model_version="m",
            explanation={"reason_codes": ["a"], "signal_milli": {}}, signature="s", outcome="accept",
            received_at_ms=started, session_started_at_ms=started))
    db.commit()


def remaining(db):
    return {sid: n for sid, n in db.execute(
        select(ScoreEvent.session_id, func.count()).group_by(ScoreEvent.session_id))}


@pytest.fixture
def history(app, partner_key):
    """Sessions 20, 8, 7 and 3 days old (ended) and one that started today and is still running."""
    partner, _ = partner_key
    with app.state.session_factory() as db:
        make_days_exist(db, [20, 8, 7, 3, 0])
        for sid, days, status in [("old20", 20, "ended"), ("old8", 8, "ended"), ("edge7", 7, "ended"),
                                  ("recent3", 3, "ended"), ("live0", 0, "active")]:
            seed(db, partner.id, sid, days, status)
    return app


def test_nothing_is_deleted_until_a_retention_period_is_chosen(history):
    with history.state.session_factory() as db:
        before = remaining(db)
        with pytest.raises(RetentionNotConfigured, match="privacy and legal decision"):
            drop_expired(db, T0, None)
        report = run_maintenance(db, settings(), T0)
        assert report.retention_days is None and "not configured" in report.note
        assert report.partitions_dropped == [] and report.rows_deleted == 0
        assert remaining(db) == before


def test_whole_old_days_are_removed_and_the_rest_is_kept(history):
    with history.state.session_factory() as db:
        report = run_maintenance(db, settings(score_event_retention_days=7), T0)
        assert remaining(db) == {"edge7": 3, "recent3": 3, "live0": 3}
        if report.partitioned:
            assert [d["day"] for d in report.partitions_dropped] == sorted(
                {_label(TODAY - 20 * DAY_MS), _label(TODAY - 8 * DAY_MS)})
            assert all(d["rows"] == 3 for d in report.partitions_dropped)
        else:
            assert report.rows_deleted == 6
        # the period is "at least 7 days": the day 7 days ago is still inside it
        assert report.delete_before_ms == TODAY - 7 * DAY_MS


def _label(day_start):
    from app.retention import _day_label
    return _day_label(day_start)


def test_a_second_run_changes_nothing_and_does_not_fail(history):
    with history.state.session_factory() as db:
        run_maintenance(db, settings(score_event_retention_days=7), T0)
        again = run_maintenance(db, settings(score_event_retention_days=7), T0)
        assert again.partitions_dropped == [] and again.rows_deleted == 0
        assert again.partitions_created == []
        assert remaining(db) == {"edge7": 3, "recent3": 3, "live0": 3}


def test_a_dry_run_reports_what_would_go_and_changes_nothing(history):
    with history.state.session_factory() as db:
        before = remaining(db)
        report = run_maintenance(db, settings(score_event_retention_days=7), T0, dry_run=True)
        assert remaining(db) == before
        assert report.dry_run is True
        would_go = (sum(d["rows"] for d in report.partitions_dropped) if report.partitioned
                    else report.rows_deleted)
        assert would_go == 6
        json.dumps(report.as_dict())  # the report can be printed or logged as JSON


def test_a_day_with_an_unfinished_call_is_never_removed(app, partner_key):
    partner, _ = partner_key
    with app.state.session_factory() as db:
        make_days_exist(db, [20])
        seed(db, partner.id, "stuck", 20, status="active")
        seed(db, partner.id, "paused_one", 20, status="paused")
        report = run_maintenance(db, settings(score_event_retention_days=7), T0)
        assert remaining(db) == {"stuck": 3, "paused_one": 3}
        if report.partitioned:
            kept = report.partitions_kept_unfinished
            assert len(kept) == 1 and kept[0]["unfinished_sessions"] == 2


def test_the_period_must_be_positive_and_shorter_than_the_attestations():
    with pytest.raises(ValueError, match="at least 1"):
        settings(score_event_retention_days=0)
    with pytest.raises(ValueError, match="shorter than attestation_retention_days"):
        settings(score_event_retention_days=30, attestation_retention_days=30)
    with pytest.raises(ValueError, match="shorter than attestation_retention_days"):
        settings(score_event_retention_days=90, attestation_retention_days=30)
    ok = settings(score_event_retention_days=30, attestation_retention_days=365)
    assert (ok.score_event_retention_days, ok.attestation_retention_days) == (30, 365)
    assert settings().score_event_retention_days is None  # no default period is invented


# ---------------------------------------------------------------------------------------- Postgres


def test_events_are_stored_in_the_partition_for_the_day_the_call_started(
        postgres_only, app, client, auth, device, session, clock):
    sess, sdk = session  # the session started at T0
    with app.state.session_factory() as db:
        ensure_partitions(db, T0, 2)
    key, dev_id = device
    pkt = make_signed_packet(key, sess["id"], dev_id, "alice", 0, T0 - 1000, T0, 900, ["a"])
    url = f"/internal/v1/sessions/continuous/{sess['id']}/score-events"
    assert client.post(url, json=pkt, headers=sdk).status_code == 200
    with app.state.session_factory() as db:
        where = db.scalar(text("SELECT tableoid::regclass::text FROM continuous_score_events"))
    assert where == partition_name(TODAY)


def test_ensure_partitions_covers_yesterday_today_and_the_days_ahead(postgres_only, app):
    with app.state.session_factory() as db:
        created = ensure_partitions(db, T0, 7)
        names = {name for name, _, _ in list_partitions(db)}
        assert {partition_name(TODAY + d * DAY_MS) for d in range(-1, 8)} <= names
        assert len(created) == 9
        assert ensure_partitions(db, T0, 7) == []  # nothing left to make


def test_a_missing_partition_never_stops_uploads_and_is_repaired_later(
        postgres_only, app, client, device, session):
    sess, sdk = session
    key, dev_id = device
    url = f"/internal/v1/sessions/continuous/{sess['id']}/score-events"
    pkt = make_signed_packet(key, sess["id"], dev_id, "alice", 0, T0 - 1000, T0, 900, ["a"])
    # nobody has made the partition for T0's day, so the row goes to the catch-all partition
    assert client.post(url, json=pkt, headers=sdk).status_code == 200
    with app.state.session_factory() as db:
        assert db.scalar(text("SELECT tableoid::regclass::text FROM continuous_score_events")) \
            == "continuous_score_events_default"
        ensure_partitions(db, T0, 2)  # moves the stranded row into its day, then attaches the day
        assert db.scalar(text("SELECT tableoid::regclass::text FROM continuous_score_events")) \
            == partition_name(TODAY)
        assert db.scalar(text("SELECT COUNT(*) FROM continuous_score_events_default")) == 0
    again = client.post(url, json=pkt, headers=sdk)  # a retry of the same packet is still recognised
    assert again.status_code == 200 and again.json()["duplicate"] is True


def test_the_database_still_refuses_a_duplicate_seq_in_a_partitioned_table(
        postgres_only, app, partner_key):
    partner, _ = partner_key
    with app.state.session_factory() as db:
        make_days_exist(db, [0])
        seed(db, partner.id, "dup", 0, events=1)
        row = db.scalar(select(ScoreEvent))
        db.add(ScoreEvent(
            session_id=row.session_id, participant_ref=row.participant_ref, seq=row.seq, device_id="d",
            interval_start_ms=1, interval_end_ms=2, confidence_milli=1, model_version="m",
            explanation={}, signature="other", outcome="accept", received_at_ms=1,
            session_started_at_ms=row.session_started_at_ms))
        with pytest.raises(IntegrityError):
            db.commit()


def test_old_rows_stranded_in_the_catch_all_partition_are_deleted_but_only_for_ended_calls(
        postgres_only, app, partner_key):
    partner, _ = partner_key
    with app.state.session_factory() as db:  # no partitions for these days: rows land in the default
        seed(db, partner.id, "ended_old", 20, status="ended")
        seed(db, partner.id, "running_old", 20, status="active")
        seed(db, partner.id, "ended_recent", 2, status="ended")
        assert db.scalar(text("SELECT COUNT(*) FROM continuous_score_events_default")) == 9
        report = run_maintenance(db, settings(score_event_retention_days=7), T0)
        assert report.rows_deleted == 3
        assert remaining(db) == {"running_old": 3, "ended_recent": 3}


def test_dropped_days_leave_the_table_and_recent_days_stay_attached(postgres_only, history):
    with history.state.session_factory() as db:
        run_maintenance(db, settings(score_event_retention_days=7), T0)
        names = {name for name, _, _ in list_partitions(db)}
        assert partition_name(TODAY - 20 * DAY_MS) not in names
        assert partition_name(TODAY - 8 * DAY_MS) not in names
        assert {partition_name(TODAY - 7 * DAY_MS), partition_name(TODAY - 3 * DAY_MS),
                partition_name(TODAY)} <= names
        gone = db.scalar(text("SELECT to_regclass(:n)"), {"n": partition_name(TODAY - 20 * DAY_MS)})
        assert gone is None  # really dropped, not just detached
