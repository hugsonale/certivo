"""Run the daily maintenance once: make tomorrow's partitions, then remove expired score events.

    python scripts/run_maintenance.py            # do it
    python scripts/run_maintenance.py --dry-run  # show what WOULD be removed, change nothing

Run from the platform/ directory. Safe to run as often as you like. The Celery worker also runs it
every day (see app/worker.py), so this script is for running it by hand or from a scheduler.
If CERTIVO_SCORE_EVENT_RETENTION_DAYS is not set, nothing is deleted (docs/adr/0015).
"""
import json
import sys

sys.path.insert(0, ".")

from app.config import Settings  # noqa: E402
from app.db import assert_schema_current, make_engine, make_session_factory  # noqa: E402
from app.retention import run_maintenance  # noqa: E402
from app.timeutil import now_ms  # noqa: E402

if __name__ == "__main__":
    settings = Settings()
    engine = make_engine(settings.database_url, settings.db_statement_timeout_ms)
    assert_schema_current(engine)
    with make_session_factory(engine)() as db:
        report = run_maintenance(db, settings, now_ms(), dry_run="--dry-run" in sys.argv)
    print(json.dumps(report.as_dict(), indent=2))
