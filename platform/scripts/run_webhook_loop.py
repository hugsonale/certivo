"""DEVELOPMENT CONVENIENCE: deliver webhooks with a plain loop, no Redis and no Celery.

Handy on a Windows PC where Redis is awkward to run. Production uses the Celery worker
(`celery -A app.worker worker --beat -Q webhooks`); this does the same steps in one process.
Run from the platform/ folder:   python scripts/run_webhook_loop.py
"""
import sys
import time

sys.path.insert(0, ".")

from app.config import Settings  # noqa: E402
from app.db import assert_schema_current, make_engine, make_session_factory  # noqa: E402
from app.secretbox import load_secretbox  # noqa: E402
from app.timeutil import now_ms  # noqa: E402
from app.webhook_engine import WebhookEngine  # noqa: E402

settings = Settings()
db_engine = make_engine(settings.database_url, settings.db_statement_timeout_ms)
assert_schema_current(db_engine)
engine = WebhookEngine(settings, make_session_factory(db_engine), now_ms, load_secretbox(settings))
print(f"Delivering webhooks every {settings.webhook_poll_interval_s}s. Press Ctrl+C to stop.")
try:
    while True:
        counts = engine.run_once()
        if any(counts.values()):
            print(time.strftime("%H:%M:%S"), counts, flush=True)
        time.sleep(settings.webhook_poll_interval_s)
except KeyboardInterrupt:
    print("stopped")
