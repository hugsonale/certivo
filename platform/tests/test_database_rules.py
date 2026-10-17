"""Rules the database itself must enforce, on SQLite and Postgres alike."""
import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.admin import ensure_default_policy
from app.models import Policy, ScoreEvent, WebhookOutbox, new_id
from app.policy import DEFAULT_POLICY_CONFIG, DEFAULT_USE_CASE


def _policy(partner_id=None, use_case="x_case", version=1):
    return Policy(id=new_id("pol"), partner_id=partner_id, use_case=use_case, version=version,
                  config=dict(DEFAULT_POLICY_CONFIG), created_at_ms=1)


def test_two_global_policies_cannot_share_use_case_and_version(app):
    with app.state.session_factory() as db:
        db.add(_policy())
        db.commit()
        db.add(_policy())  # partner_id is NULL on both: a plain UNIQUE would let this through
        with pytest.raises(IntegrityError):
            db.commit()


def test_global_policy_may_have_a_new_version_or_use_case(app):
    with app.state.session_factory() as db:
        db.add_all([_policy(), _policy(version=2), _policy(use_case="other_case")])
        db.commit()


def test_partner_policy_may_reuse_a_global_use_case(app, partner_key):
    partner, _ = partner_key
    with app.state.session_factory() as db:
        db.add_all([_policy(), _policy(partner_id=partner.id)])
        db.commit()


def test_default_policy_is_seeded_once_even_if_asked_repeatedly(app):
    with app.state.session_factory() as db:
        for _ in range(3):
            ensure_default_policy(db)
            db.commit()
        count = db.scalar(select(func.count()).select_from(Policy).where(
            Policy.partner_id.is_(None), Policy.use_case == DEFAULT_USE_CASE))
    assert count == 1


def test_policy_config_survives_a_database_round_trip(app):
    with app.state.session_factory() as db:
        stored = db.scalar(select(Policy).where(Policy.use_case == DEFAULT_USE_CASE))
    assert stored.config == DEFAULT_POLICY_CONFIG


def test_database_rejects_a_duplicate_score_event_sequence(app, device, session):
    sess, _ = session
    row = dict(session_id=sess["id"], participant_ref="alice", seq=7, device_id=device[1],
               interval_start_ms=1, interval_end_ms=2, confidence_milli=900,
               model_version="m", explanation={"reason_codes": ["a"], "signal_milli": {}},
               signature="s", outcome="accept", received_at_ms=3, session_started_at_ms=4)
    with app.state.session_factory() as db:
        db.add(ScoreEvent(**row))
        db.commit()
        db.add(ScoreEvent(**row))
        with pytest.raises(IntegrityError):
            db.commit()


def test_auto_increment_ids_are_assigned_and_increase(app, partner_key):
    partner, _ = partner_key
    with app.state.session_factory() as db:
        for i in range(3):
            db.add(WebhookOutbox(event_id=new_id("evt"), partner_id=partner.id, event_type="t",
                                 payload={"i": i}, created_at_ms=1))
        db.commit()
        ids = list(db.scalars(select(WebhookOutbox.id).order_by(WebhookOutbox.id)))
    assert len(ids) == 3 and ids == sorted(set(ids))
