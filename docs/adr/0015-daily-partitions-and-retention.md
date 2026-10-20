# ADR 0015: Daily partitions of the score-events table, and retention

- **Date:** 2026-10-17
- **Status:** Proposed (waiting for Jesutofunmi to approve)
- **Decision register / step IDs:** P0-09, P0-52 (sets the retention period), P0-13 (audit log)

## Context

Per-interval scores are the highest-volume table, and the data we want to hold for the shortest time: the signed attestation is the lasting record. Database Design section 4 asks for daily partitions of that table and a retention job that drops whole days on a schedule shorter than the attestation's. Privacy Architecture section 2.2 says the attestation's own retention period is deferred to the privacy review, so no number exists yet.

Postgres has one hard rule that shapes the design: a unique rule on a partitioned table must include the partition column. Our rule "one row per session, participant and seq" is what makes a resent packet harmless.

## Options considered

1. **Partition by the time we received the row (as the Database Design doc's `reported_at` suggests).** A retry of one packet arrives at a different time, so it can land in a different partition and the unique rule would no longer catch it. We would have to rebuild that protection with locks in the application.
2. **Partition by the packet's own interval time.** A device with a wrong clock could ask for a partition that does not exist or was already dropped.
3. **Partition by the start time of the call the row belongs to.** Every row of a call has the same value, so the unique rule keeps its exact meaning, the value is set by our server and never changes, and every query can name it.

## Decision

Option 3. `session_started_at_ms` is copied onto each score event and is the partition key (one partition per UTC day). It is part of the unique rule, which still means one row per session, participant and seq.

- **Every query names the day.** Postgres then reads exactly one partition no matter how many days we keep. This is checked against the real statements with EXPLAIN (`tests/test_query_plans.py`).
- **A catch-all partition** receives a row if a day's partition is ever missing, so a missed maintenance run cannot stop uploads. The next run moves such rows into their day.
- **Maintenance** (`scripts/run_maintenance.py`, and a Celery beat task at 03:15) makes partitions for yesterday, today and the next 7 days, then enforces retention.
- **Retention has no default.** If `CERTIVO_SCORE_EVENT_RETENTION_DAYS` is not set the job deletes nothing and says so. When it is set, the job drops every whole day older than it, so data is kept for at least that many days and removed within one more day. If `CERTIVO_ATTESTATION_RETENTION_DAYS` is also set, the score-event period must be shorter, or the app refuses to start. Nothing deletes attestations yet.
- **Safety:** a day is never dropped while any call that started on it has not ended. Old rows stranded in the catch-all partition are deleted row by row, only for ended calls. DDL gives up after 5 seconds rather than make uploads wait.
- **SQLite (development) keeps one plain table**; the same rule deletes rows. Only Postgres is partitioned.
- **Indexes (Database Design section 3).** No new index was added. The unique index, which already leads with `session_id`, serves every lookup, the "latest K" read (scanned backwards) and the whole-session read. The index on `reported_at` is not needed because dropping a day removes a partition by name and no query filters by time yet. Revisit when partner analytics (P1-11) filter by time.
- `GET .../status` now reads the newest row and a count instead of every row, because partners poll it.

## Consequences

The database no longer enforces the unique rule across days on its own, but because every row of a call shares one day, in practice it does exactly what it did. `alembic` ignores the daily partitions (they are managed by `app/retention.py`). The migration rebuilds the table and keeps every row and ID; it suits the current size and should be rehearsed on a copy before running against a large production table. **The retention period must be chosen in P0-52 before launch, or data is kept forever.** Dropping a partition takes a brief lock on the table. The attestation-retention setting exists only so the "shorter than the attestation" rule is checked as soon as both numbers exist.
