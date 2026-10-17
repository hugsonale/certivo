"""daily partitions for continuous_score_events

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-17

Build step P0-09 (docs/adr/0015). Adds `session_started_at_ms` to every score event: a copy of the
start time of the call it belongs to. On Postgres the table is rebuilt as a table split into one
partition per day of that column; on SQLite (development) it stays one plain table.

Rows already in the table are kept, with their IDs. A partition is made for every day that has data,
for yesterday and today and the next seven days, and there is a "default" partition that catches a
row if the day's partition is ever missing, so a missed maintenance run can never stop uploads.
After this migration `python scripts/run_maintenance.py` keeps the partitions ahead of the clock.

The unique rule on (session, participant, seq) now also lists `session_started_at_ms`. Postgres
insists on that for a partitioned table. Every row of a session has the same value, so the rule still
means exactly what it did.
"""
from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "continuous_score_events"
UNIQUE = "uq_score_events_session_participant_seq"
DAY_MS = 86_400_000
BASE_COLUMNS = ("id, session_id, participant_ref, seq, device_id, interval_start_ms, interval_end_ms, "
                "confidence_milli, model_version, explanation, signature, outcome, received_at_ms")

COLUMN_DEFINITIONS = """
    id BIGSERIAL NOT NULL,
    session_id VARCHAR(64) NOT NULL,
    participant_ref VARCHAR(64) NOT NULL,
    seq INTEGER NOT NULL,
    device_id VARCHAR(64) NOT NULL,
    interval_start_ms BIGINT NOT NULL,
    interval_end_ms BIGINT NOT NULL,
    confidence_milli INTEGER NOT NULL,
    model_version VARCHAR(64) NOT NULL,
    explanation JSONB NOT NULL,
    signature VARCHAR(100) NOT NULL,
    outcome VARCHAR(16) NOT NULL,
    received_at_ms BIGINT NOT NULL,
"""
FOREIGN_KEY = ("CONSTRAINT fk_continuous_score_events_session_id_continuous_sessions "
               "FOREIGN KEY (session_id) REFERENCES continuous_sessions (id)")


def _day_name(day_start_ms: int) -> str:
    return "continuous_score_events_p" + datetime.fromtimestamp(day_start_ms / 1000, UTC).strftime("%Y%m%d")


def _rename_back(from_suffix: str) -> None:
    op.execute(f"ALTER TABLE {TABLE}{from_suffix} RENAME TO {TABLE}")
    op.execute(f"ALTER TABLE {TABLE} RENAME CONSTRAINT pk_{TABLE}{from_suffix} TO pk_{TABLE}")
    op.execute(f"ALTER TABLE {TABLE} RENAME CONSTRAINT {UNIQUE}{from_suffix} TO {UNIQUE}")
    op.execute(f"ALTER SEQUENCE {TABLE}{from_suffix}_id_seq RENAME TO {TABLE}_id_seq")


def _copy_ids_forward() -> None:
    """Make the new table's counter carry on after the highest ID that was copied across."""
    new = f"{TABLE}_new" if op.get_bind().dialect.name == "postgresql" else TABLE
    op.execute(f"SELECT setval(pg_get_serial_sequence('{new}', 'id'), "
               f"COALESCE((SELECT MAX(id) FROM {TABLE}), 1), (SELECT COUNT(*) > 0 FROM {TABLE}))")


def upgrade() -> None:
    op.add_column(TABLE, sa.Column("session_started_at_ms", sa.BigInteger(), nullable=True))
    op.execute(
        f"UPDATE {TABLE} SET session_started_at_ms = COALESCE("
        f"(SELECT started_at_ms FROM continuous_sessions WHERE continuous_sessions.id = {TABLE}.session_id), "
        f"received_at_ms)")

    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        with op.batch_alter_table(TABLE) as batch:
            batch.alter_column("session_started_at_ms", existing_type=sa.BigInteger(), nullable=False)
            batch.drop_constraint(UNIQUE, type_="unique")
            batch.create_unique_constraint(
                UNIQUE, ["session_id", "participant_ref", "seq", "session_started_at_ms"])
        return

    op.execute(f"""
        CREATE TABLE {TABLE}_new ({COLUMN_DEFINITIONS}
            session_started_at_ms BIGINT NOT NULL,
            CONSTRAINT pk_{TABLE}_new PRIMARY KEY (id, session_started_at_ms),
            CONSTRAINT {UNIQUE}_new UNIQUE (session_id, participant_ref, seq, session_started_at_ms),
            {FOREIGN_KEY}
        ) PARTITION BY RANGE (session_started_at_ms)""")
    op.execute(f"CREATE TABLE {TABLE}_default PARTITION OF {TABLE}_new DEFAULT")

    days = {row[0] for row in bind.execute(
        sa.text(f"SELECT DISTINCT session_started_at_ms / {DAY_MS} FROM {TABLE}"))}
    today = bind.execute(sa.text(f"SELECT (EXTRACT(EPOCH FROM now()) * 1000)::bigint / {DAY_MS}")).scalar()
    days |= set(range(today - 1, today + 8))
    for day in sorted(days):
        low = int(day) * DAY_MS
        op.execute(f"CREATE TABLE {_day_name(low)} PARTITION OF {TABLE}_new "
                   f"FOR VALUES FROM ({low}) TO ({low + DAY_MS})")

    op.execute(f"INSERT INTO {TABLE}_new ({BASE_COLUMNS}, session_started_at_ms) "
               f"SELECT {BASE_COLUMNS}, session_started_at_ms FROM {TABLE}")
    _copy_ids_forward()
    op.execute(f"DROP TABLE {TABLE}")
    _rename_back("_new")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        with op.batch_alter_table(TABLE) as batch:
            batch.drop_constraint(UNIQUE, type_="unique")
            batch.create_unique_constraint(UNIQUE, ["session_id", "participant_ref", "seq"])
            batch.drop_column("session_started_at_ms")
        return

    op.execute(f"""
        CREATE TABLE {TABLE}_old ({COLUMN_DEFINITIONS.rstrip().rstrip(',')},
            CONSTRAINT pk_{TABLE}_old PRIMARY KEY (id),
            CONSTRAINT {UNIQUE}_old UNIQUE (session_id, participant_ref, seq),
            {FOREIGN_KEY}
        )""")
    op.execute(f"INSERT INTO {TABLE}_old ({BASE_COLUMNS}) SELECT {BASE_COLUMNS} FROM {TABLE}")
    op.execute(f"SELECT setval(pg_get_serial_sequence('{TABLE}_old', 'id'), "
               f"COALESCE((SELECT MAX(id) FROM {TABLE}), 1), (SELECT COUNT(*) > 0 FROM {TABLE}))")
    op.execute(f"DROP TABLE {TABLE}")  # also drops every partition
    _rename_back("_old")
