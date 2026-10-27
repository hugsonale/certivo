"""Print the audit log, newest first.   python scripts/list_audit.py [--partner ptn_...] [--action api_key.created] [--limit 50]

Read-only. Uses CERTIVO_DATABASE_URL like the rest of the platform."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.config import Settings  # noqa: E402
from app.db import make_engine, make_session_factory  # noqa: E402
from app.models import AuditEvent  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--partner", help="only changes to this partner's data")
    parser.add_argument("--action", help="only this action, for example api_key.revoked")
    parser.add_argument("--limit", type=int, default=50)
    args = parser.parse_args()

    settings = Settings()
    engine = make_engine(settings.database_url, settings.db_statement_timeout_ms)
    query = select(AuditEvent).order_by(AuditEvent.id.desc()).limit(max(1, args.limit))
    if args.partner:
        query = query.where(AuditEvent.partner_id == args.partner)
    if args.action:
        query = query.where(AuditEvent.action == args.action)
    with make_session_factory(engine)() as db:
        rows = list(db.scalars(query))
    if not rows:
        print("No audit records match.")
    for e in rows:
        when = datetime.fromtimestamp(e.at_ms / 1000, tz=UTC).strftime("%Y-%m-%d %H:%M:%S")
        actor = e.actor_type + (f":{e.actor_id}" if e.actor_id else "")
        print(f"{when}Z  {e.action:<34} by {actor:<40} target={e.target_type}:{e.target_id}  "
              f"request={e.request_id or '-'}  {json.dumps(e.details, sort_keys=True)}")
    engine.dispose()


if __name__ == "__main__":
    main()
