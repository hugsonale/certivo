"""P0-09: the score-events queries really use the intended indexes and read only one daily partition.

These run the application's own statements through Postgres's EXPLAIN. `enable_seqscan` is switched
off so the plan shows whether an index CAN serve the query (on a small test table Postgres would
sometimes prefer reading everything, which says nothing about production). SQLite is skipped:
it has no partitions and nothing here applies.
"""
import pytest
from sqlalchemy import insert, select, text

from app.models import ContinuousSession, ScoreEvent
from app.retention import DAY_MS, create_day_partition, day_start_ms
from app.services import sessions as svc
from tests.conftest import T0

TODAY = day_start_ms(T0)
DAYS, SESSIONS_PER_DAY, PARTICIPANTS, EVENTS = 3, 12, 2, 60


@pytest.fixture(autouse=True)
def _postgres_only(db_url):
    if not db_url.startswith("postgresql"):
        pytest.skip("Postgres only")


@pytest.fixture
def busy_table(app, partner_key):
    """Three daily partitions, each holding 12 sessions x 2 participants x 60 events."""
    partner, _ = partner_key
    with app.state.session_factory() as db:
        rows = []
        for day in range(DAYS):
            start_of_day = TODAY - day * DAY_MS
            create_day_partition(db, start_of_day)
            for n in range(SESSIONS_PER_DAY):
                started = start_of_day + 60_000 * (n + 1)
                db.add(ContinuousSession(
                    id=f"cs_{day}_{n}", partner_id=partner.id, use_case="u", policy_id="p", policy_version=1,
                    policy_config={"drop_consecutive": 2}, status="active", started_at_ms=started,
                    sdk_token_hash="t" * 64, sdk_token_expires_at_ms=started + 1))
                for ref in range(PARTICIPANTS):
                    for seq in range(EVENTS):
                        rows.append(dict(
                            session_id=f"cs_{day}_{n}", participant_ref=f"p{ref}", seq=seq, device_id="d",
                            interval_start_ms=started, interval_end_ms=started + 1000,
                            confidence_milli=900, model_version="m", explanation={"reason_codes": []},
                            signature="s", outcome="accept", received_at_ms=started,
                            session_started_at_ms=started))
        db.commit()
        db.execute(insert(ScoreEvent), rows)
        db.commit()
        db.execute(text("ANALYZE continuous_score_events"))
        db.commit()
        yield db


def explain(db, stmt, **planner_off):
    sql = str(stmt.compile(dialect=db.get_bind().dialect, compile_kwargs={"literal_binds": True}))
    db.execute(text("SET LOCAL enable_seqscan = off"))
    for setting in planner_off:
        db.execute(text(f"SET LOCAL {setting} = off"))
    return db.execute(text("EXPLAIN (FORMAT JSON) " + sql)).scalar()[0]["Plan"]


def walk(plan):
    yield plan
    for child in plan.get("Plans", []):
        yield from walk(child)


def facts(plan):
    nodes = list(walk(plan))
    return {
        "types": {n["Node Type"] for n in nodes},
        "partitions": {n["Relation Name"] for n in nodes
                       if n.get("Relation Name", "").startswith("continuous_score_events_")},
        "backward": any(n.get("Scan Direction") == "Backward" for n in nodes),
    }


@pytest.fixture
def one_session(busy_table):
    return busy_table.get(ContinuousSession, "cs_1_5")


def test_looking_up_one_packet_uses_the_unique_index_on_one_partition(busy_table, one_session):
    f = facts(explain(busy_table, svc.event_lookup_stmt(one_session, "p1", 17)))
    assert f["types"] & {"Index Scan", "Index Only Scan"} and "Seq Scan" not in f["types"]
    assert len(f["partitions"]) == 1  # the other two days and the catch-all are never opened


def test_the_latest_scores_come_straight_off_the_index_in_order(busy_table, one_session):
    f = facts(explain(busy_table, svc.recent_events_stmt(one_session, "p0", 2)))
    assert f["types"] & {"Index Scan", "Index Only Scan"} and "Seq Scan" not in f["types"]
    assert f["backward"] and "Sort" not in f["types"]  # newest first, no sorting step
    assert len(f["partitions"]) == 1


def test_reading_a_whole_session_uses_the_index_and_one_partition(busy_table, one_session):
    f = facts(explain(busy_table, svc.session_events_stmt(one_session)))
    assert f["types"] & {"Index Scan", "Index Only Scan", "Bitmap Index Scan"}
    assert "Seq Scan" not in f["types"] and len(f["partitions"]) == 1


def test_the_index_can_hand_back_a_whole_session_already_in_order(busy_table, one_session):
    """For a call of this size Postgres may choose to fetch the rows and sort them (cheap, and done
    once when the call ends). This shows the index also CAN supply participant_ref, seq order itself."""
    f = facts(explain(busy_table, svc.session_events_stmt(one_session), enable_bitmapscan=True))
    assert f["types"] & {"Index Scan", "Index Only Scan"} and "Sort" not in f["types"]
    assert len(f["partitions"]) == 1


def test_listing_participants_and_counting_events_use_the_index(busy_table, one_session):
    for stmt in (svc.participant_refs_stmt(one_session), svc.event_count_stmt(one_session, "p1")):
        f = facts(explain(busy_table, stmt))
        assert "Seq Scan" not in f["types"] and len(f["partitions"]) == 1


def test_without_the_day_in_the_query_every_partition_would_be_opened(busy_table, one_session):
    """Why every query names the day: the same lookup without it touches all the partitions."""
    unpruned = select(ScoreEvent).where(
        ScoreEvent.session_id == one_session.id, ScoreEvent.participant_ref == "p1", ScoreEvent.seq == 17)
    f = facts(explain(busy_table, unpruned))
    assert len(f["partitions"]) > DAYS  # the three days plus the catch-all
    assert len(facts(explain(busy_table, svc.event_lookup_stmt(one_session, "p1", 17)))["partitions"]) == 1


def test_the_real_service_calls_return_the_right_rows(busy_table, one_session):
    """The faster statements still answer the same questions."""
    assert [e.seq for e in busy_table.scalars(svc.recent_events_stmt(one_session, "p0", 3))] == [59, 58, 57]
    assert busy_table.scalar(svc.event_count_stmt(one_session, "p1")) == EVENTS
    assert sorted(busy_table.scalars(svc.participant_refs_stmt(one_session))) == ["p0", "p1"]
    assert len(list(busy_table.scalars(svc.session_events_stmt(one_session)))) == PARTICIPANTS * EVENTS
