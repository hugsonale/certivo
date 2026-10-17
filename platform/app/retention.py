"""Daily partitions of continuous_score_events, and the job that enforces retention (P0-09).

Per-interval scores are the highest-volume table and the data we most want to hold only briefly (the
signed attestation is the lasting record). On Postgres the table is split into one partition per day
of `session_started_at_ms`, so enforcing retention means dropping whole old days, which is instant,
instead of deleting millions of rows one by one. On SQLite (development) the table is a plain one and
the same rule is applied with an ordinary DELETE.

Run once a day:  python scripts/run_maintenance.py     (or let the Celery beat timer do it)

What the job does, in order:
  1. Postgres only: make sure there is a partition for yesterday, today and the next few days.
  2. If a retention period is configured: remove every day that is entirely older than it.
     If it is NOT configured the job deletes nothing and says so. No number has been chosen: how long
     to keep data is a privacy and legal decision (P0-52, docs/adr/0015).

Safety rules:
  * a day is never removed while any call that started on it is still unfinished;
  * a day is removed only when every row in it is older than the retention period;
  * the per-day work takes short locks and gives up after five seconds instead of making uploads wait.
"""
from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime

from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import ContinuousSession, ScoreEvent

log = logging.getLogger("certivo.retention")

DAY_MS = 86_400_000
PARENT = "continuous_score_events"
DEFAULT_PARTITION = f"{PARENT}_default"
_BOUNDS = re.compile(r"FROM \('?(-?\d+)'?\) TO \('?(-?\d+)'?\)")


class RetentionNotConfigured(RuntimeError):
    """No retention period has been chosen, so there is nothing safe to delete."""


@dataclass
class MaintenanceReport:
    partitioned: bool
    dry_run: bool
    retention_days: int | None
    delete_before_ms: int | None = None  # whole days that start before this are removed
    partitions_created: list[str] = field(default_factory=list)
    partitions_dropped: list[dict] = field(default_factory=list)  # name, day, rows
    partitions_kept_unfinished: list[dict] = field(default_factory=list)  # name, day, unfinished_sessions
    rows_deleted: int = 0  # rows removed one by one (SQLite, or old rows stranded in the default partition)
    note: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


def day_start_ms(ms: int) -> int:
    return ms - ms % DAY_MS


def partition_name(day_start: int) -> str:
    return f"{PARENT}_p" + datetime.fromtimestamp(day_start / 1000, UTC).strftime("%Y%m%d")


def _day_label(day_start: int) -> str:
    return datetime.fromtimestamp(day_start / 1000, UTC).strftime("%Y-%m-%d")


def is_partitioned(db: Session) -> bool:
    if db.get_bind().dialect.name != "postgresql":
        return False
    return db.scalar(text("SELECT 1 FROM pg_partitioned_table WHERE partrelid = to_regclass(:t)"),
                     {"t": PARENT}) is not None


def list_partitions(db: Session) -> list[tuple[str, int, int]]:
    """(name, first ms, last ms + 1) of every daily partition, oldest first. Not the default one."""
    rows = db.execute(text(
        "SELECT c.relname, pg_get_expr(c.relpartbound, c.oid) FROM pg_inherits i "
        "JOIN pg_class c ON c.oid = i.inhrelid WHERE i.inhparent = to_regclass(:t)"), {"t": PARENT})
    found = []
    for name, bound in rows:
        match = _BOUNDS.search(bound or "")
        if match:  # the DEFAULT partition has no bounds
            found.append((name, int(match.group(1)), int(match.group(2))))
    return sorted(found, key=lambda p: p[1])


def _short_locks(db: Session) -> None:
    db.execute(text("SET LOCAL lock_timeout = '5s'"))


def create_day_partition(db: Session, day_start: int) -> str:
    """Add the partition for one day. If rows for that day already landed in the default partition
    (a missed maintenance run), move them in rather than failing."""
    _short_locks(db)
    name, low, high = partition_name(day_start), day_start, day_start + DAY_MS
    stranded = db.scalar(text(
        f"SELECT COUNT(*) FROM {DEFAULT_PARTITION} "
        "WHERE session_started_at_ms >= :lo AND session_started_at_ms < :hi"), {"lo": low, "hi": high})
    if not stranded:
        db.execute(text(f"CREATE TABLE {name} PARTITION OF {PARENT} FOR VALUES FROM ({low}) TO ({high})"))
    else:
        db.execute(text(f"CREATE TABLE {name} (LIKE {PARENT} INCLUDING DEFAULTS INCLUDING CONSTRAINTS)"))
        db.execute(text(
            f"WITH moved AS (DELETE FROM {DEFAULT_PARTITION} WHERE session_started_at_ms >= :lo "
            f"AND session_started_at_ms < :hi RETURNING *) INSERT INTO {name} SELECT * FROM moved"),
            {"lo": low, "hi": high})
        db.execute(text(f"ALTER TABLE {PARENT} ATTACH PARTITION {name} FOR VALUES FROM ({low}) TO ({high})"))
    return name


def ensure_partitions(db: Session, now_ms: int, days_ahead: int) -> list[str]:
    """Make sure yesterday, today and the next `days_ahead` days each have a partition."""
    if not is_partitioned(db):
        return []
    have = {low for _, low, _ in list_partitions(db)}
    created = []
    today = day_start_ms(now_ms)
    for day in range(today - DAY_MS, today + (days_ahead + 1) * DAY_MS, DAY_MS):
        if day not in have:
            created.append(create_day_partition(db, day))
            db.commit()
    return created


def _unfinished_sessions(db: Session, low: int, high: int) -> int:
    return db.scalar(select(func.count()).select_from(ContinuousSession).where(
        ContinuousSession.started_at_ms >= low, ContinuousSession.started_at_ms < high,
        ContinuousSession.status != "ended")) or 0


def _old_finished_rows(boundary: int):
    ended = select(ContinuousSession.id).where(ContinuousSession.status == "ended")
    return (ScoreEvent.session_started_at_ms < boundary, ScoreEvent.session_id.in_(ended))


def drop_expired(db: Session, now_ms: int, retention_days: int | None,
                 dry_run: bool = False) -> MaintenanceReport:
    """Remove every day of score events that is entirely older than the retention period."""
    if retention_days is None:
        raise RetentionNotConfigured(
            "CERTIVO_SCORE_EVENT_RETENTION_DAYS is not set. How long to keep score events is a "
            "privacy and legal decision (P0-52); nothing is deleted until it is made.")
    boundary = day_start_ms(now_ms - retention_days * DAY_MS)
    partitioned = is_partitioned(db)
    report = MaintenanceReport(partitioned=partitioned, dry_run=dry_run, retention_days=retention_days,
                               delete_before_ms=boundary)

    if not partitioned:  # SQLite and other development databases
        where = _old_finished_rows(boundary)
        if dry_run:
            report.rows_deleted = db.scalar(select(func.count()).select_from(ScoreEvent).where(*where)) or 0
        else:
            report.rows_deleted = db.execute(delete(ScoreEvent).where(*where)).rowcount or 0
            db.commit()
        return report

    for name, low, high in list_partitions(db):
        if high > boundary:
            continue  # part of this day is still inside the retention period
        entry = {"partition": name, "day": _day_label(low)}
        unfinished = _unfinished_sessions(db, low, high)
        if unfinished:
            report.partitions_kept_unfinished.append({**entry, "unfinished_sessions": unfinished})
            log.warning("keeping %s: %d call(s) that started that day have not ended", name, unfinished)
            continue
        entry["rows"] = db.scalar(text(f"SELECT COUNT(*) FROM {name}"))
        if not dry_run:
            _short_locks(db)
            db.execute(text(f"ALTER TABLE {PARENT} DETACH PARTITION {name}"))
            db.execute(text(f"DROP TABLE {name}"))
            db.commit()
            log.info("dropped %s (%s rows)", name, entry["rows"])
        report.partitions_dropped.append(entry)

    # Old rows that landed in the default partition (a missed maintenance run) cannot be dropped as a
    # whole day, so they are deleted row by row, and only for calls that have ended.
    stranded = (f"FROM {DEFAULT_PARTITION} WHERE session_started_at_ms < :b AND session_id IN "
                "(SELECT id FROM continuous_sessions WHERE status = 'ended')")
    if dry_run:
        report.rows_deleted = db.scalar(text(f"SELECT COUNT(*) {stranded}"), {"b": boundary}) or 0
    else:
        report.rows_deleted = db.execute(text(f"DELETE {stranded}"), {"b": boundary}).rowcount or 0
        db.commit()
    return report


def run_maintenance(db: Session, settings: Settings, now_ms: int, dry_run: bool = False) -> MaintenanceReport:
    """The daily job: partitions first, then retention if (and only if) a period is configured."""
    created: list[str] = []
    if not dry_run:
        created = ensure_partitions(db, now_ms, settings.partition_days_ahead)
    if settings.score_event_retention_days is None:
        log.warning("No score-event retention period is configured, so nothing was deleted.")
        return MaintenanceReport(
            partitioned=is_partitioned(db), dry_run=dry_run, retention_days=None,
            partitions_created=created,
            note="retention is not configured (CERTIVO_SCORE_EVENT_RETENTION_DAYS); nothing deleted")
    report = drop_expired(db, now_ms, settings.score_event_retention_days, dry_run=dry_run)
    report.partitions_created = created
    return report
