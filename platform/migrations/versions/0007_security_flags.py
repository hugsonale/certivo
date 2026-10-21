"""security flags and how each score reached us

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-20

Build step P0-12 (docs/adr/0018).

* `security_flags`: implausible score patterns noticed by app/anomaly.py. Internal signals only.
* `continuous_score_events.received_via`: `live` or `batch`. Packets uploaded after an outage arrive in a
  burst on purpose, so the timing checks must be able to tell them apart. Existing rows count as live.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | Sequence[str] | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONType = sa.JSON().with_variant(sa.dialects.postgresql.JSONB(), "postgresql")
BigIntId = sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def upgrade() -> None:
    op.add_column("continuous_score_events",
                  sa.Column("received_via", sa.String(8), nullable=False, server_default="live"))
    op.create_table(
        "security_flags",
        sa.Column("id", BigIntId, autoincrement=True, nullable=False),
        sa.Column("session_id", sa.String(), nullable=False),
        sa.Column("partner_id", sa.String(64), nullable=False),
        sa.Column("participant_ref", sa.String(64), nullable=False),
        sa.Column("device_id", sa.String(64), nullable=False),
        sa.Column("flag_type", sa.String(40), nullable=False),
        sa.Column("detail", JSONType, nullable=False),
        sa.Column("first_seq", sa.Integer(), nullable=False),
        sa.Column("last_seq", sa.Integer(), nullable=False),
        sa.Column("raised_at_ms", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["continuous_sessions.id"],
                                name="fk_security_flags_session_id_continuous_sessions"),
        sa.PrimaryKeyConstraint("id", name="pk_security_flags"),
    )
    op.create_index("ix_security_flags_raised_at", "security_flags", ["raised_at_ms"])
    op.create_index("ix_security_flags_session", "security_flags", ["session_id"])


def downgrade() -> None:
    op.drop_table("security_flags")
    if op.get_bind().dialect.name == "postgresql":
        op.drop_column("continuous_score_events", "received_via")
    else:
        with op.batch_alter_table("continuous_score_events") as batch:
            batch.drop_column("received_via")
