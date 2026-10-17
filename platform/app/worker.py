"""The Celery worker that delivers webhooks.   celery -A app.worker worker --beat -Q webhooks

A "beat" timer runs `poll` every few seconds. `poll` turns new events into deliveries, locks the ones
that are due and hands each to a `deliver` task. All the real logic and all the state live in
app/webhook_engine.py and the database; Celery and Redis only decide when it runs. If Redis is lost
nothing is lost: deliveries stay in the database and are picked up again afterwards.
"""
from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from app.config import Settings
from app.db import assert_schema_current, make_engine, make_session_factory
from app.retention import run_maintenance
from app.secretbox import load_secretbox
from app.timeutil import now_ms
from app.webhook_engine import WebhookEngine

_settings = Settings()

celery_app = Celery("certivo", broker=_settings.redis_url)
celery_app.conf.update(
    task_default_queue="webhooks",
    task_serializer="json",
    accept_content=["json"],
    task_ignore_result=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
    timezone="UTC",
    enable_utc=True,
    beat_schedule={
        "certivo-webhook-poll": {"task": "certivo.webhooks.poll",
                                 "schedule": _settings.webhook_poll_interval_s},
        # Daily, at a quiet hour: tomorrow's partitions, then retention (app/retention.py).
        "certivo-daily-maintenance": {"task": "certivo.maintenance.run",
                                      "schedule": crontab(hour=3, minute=15)},
    },
)

_engine: WebhookEngine | None = None


def get_engine() -> WebhookEngine:
    """Built on first use, so importing this module never touches the database."""
    global _engine
    if _engine is None:
        settings = Settings()
        db_engine = make_engine(settings.database_url, settings.db_statement_timeout_ms)
        assert_schema_current(db_engine)  # clear message if `alembic upgrade head` has not been run
        _engine = WebhookEngine(settings, make_session_factory(db_engine), now_ms,
                                load_secretbox(settings))
    return _engine


def set_engine_for_tests(engine: WebhookEngine | None) -> None:
    global _engine
    _engine = engine


@celery_app.task(name="certivo.webhooks.poll")
def poll() -> int:
    engine = get_engine()
    engine.fan_out()
    claimed = engine.claim_due()
    for delivery_id, token in claimed:
        deliver.delay(delivery_id, token)
    return len(claimed)


@celery_app.task(name="certivo.webhooks.deliver", soft_time_limit=120)
def deliver(delivery_id: str, claim_token: str) -> str:
    return get_engine().attempt(delivery_id, claim_token)


@celery_app.task(name="certivo.maintenance.run", soft_time_limit=600)
def maintenance() -> dict:
    """Partitions ahead of the clock, and retention if a period is configured."""
    settings = Settings()
    db_engine = make_engine(settings.database_url, settings.db_statement_timeout_ms)
    try:
        assert_schema_current(db_engine)
        with make_session_factory(db_engine)() as db:
            return run_maintenance(db, settings, now_ms()).as_dict()
    finally:
        db_engine.dispose()
