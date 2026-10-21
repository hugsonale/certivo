"""Show the implausible-pattern flags that have been raised (ADR 0018). Read-only.

    python scripts/list_flags.py              # the 50 most recent
    python scripts/list_flags.py --limit 200
    python scripts/list_flags.py --session cs_xxxxxxxx

Flags are internal security signals for the incident-response process. Partners never see them and they
never change a decision, so this is the only place to look at them. Run from the platform/ directory.
"""
import sys
from datetime import UTC, datetime

sys.path.insert(0, ".")

from sqlalchemy import select  # noqa: E402

from app.config import Settings  # noqa: E402
from app.db import assert_schema_current, make_engine, make_session_factory  # noqa: E402
from app.models import SecurityFlag  # noqa: E402


def option(name: str, default: str | None = None) -> str | None:
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


if __name__ == "__main__":
    settings = Settings()
    engine = make_engine(settings.database_url, settings.db_statement_timeout_ms)
    assert_schema_current(engine)
    query = select(SecurityFlag).order_by(SecurityFlag.raised_at_ms.desc(), SecurityFlag.id.desc())
    if option("--session"):
        query = query.where(SecurityFlag.session_id == option("--session"))
    with make_session_factory(engine)() as db:
        flags = list(db.scalars(query.limit(int(option("--limit", "50")))))
    if not flags:
        print("No flags have been raised.")
    for f in flags:
        when = datetime.fromtimestamp(f.raised_at_ms / 1000, UTC).strftime("%Y-%m-%d %H:%M:%S")
        print(f"{when} UTC  {f.flag_type:<24} session={f.session_id} participant={f.participant_ref} "
              f"device={f.device_id} seq={f.first_seq}-{f.last_seq} {f.detail}")
