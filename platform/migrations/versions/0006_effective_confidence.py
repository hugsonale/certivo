"""store the effective confidence on every score event

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-19

Build step P0-11 (docs/adr/0017). The policy engine compares an EFFECTIVE confidence (the reported one
minus the device-tier and model-version penalties) with its thresholds. Both numbers are kept: the
reported value is never altered. Rows that already exist were scored with no penalties, so their effective
confidence equals the reported one.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "continuous_score_events"


def upgrade() -> None:
    op.add_column(TABLE, sa.Column("effective_confidence_milli", sa.Integer(), nullable=True))
    op.execute(f"UPDATE {TABLE} SET effective_confidence_milli = confidence_milli")
    if op.get_bind().dialect.name == "postgresql":
        op.alter_column(TABLE, "effective_confidence_milli", existing_type=sa.Integer(), nullable=False)
    else:
        with op.batch_alter_table(TABLE) as batch:
            batch.alter_column("effective_confidence_milli", existing_type=sa.Integer(), nullable=False)


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.drop_column(TABLE, "effective_confidence_milli")
    else:
        with op.batch_alter_table(TABLE) as batch:
            batch.drop_column("effective_confidence_milli")
