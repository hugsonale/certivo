"""attestation keys registry and a signing queue

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-18

Build step P0-10 (docs/adr/0016).

* `attestation_keys`: every public key the platform has signed with, kept forever, so an old
  attestation verifies after its key was retired. The app registers its key at startup.
* `session_attestations` can now hold a finished call whose attestation is not signed yet:
  `attestation` may be empty, `status` says signed or pending, and the unsigned `payload`, the retry
  count and the next attempt are kept until the signer is reachable again.

Attestations that already exist are unchanged and count as signed.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONType = sa.JSON().with_variant(sa.dialects.postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "attestation_keys",
        sa.Column("key_id", sa.String(64), nullable=False),
        sa.Column("alg", sa.String(16), nullable=False),
        sa.Column("public_key", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at_ms", sa.BigInteger(), nullable=False),
        sa.Column("retired_at_ms", sa.BigInteger(), nullable=True),
        sa.PrimaryKeyConstraint("key_id", name="pk_attestation_keys"),
    )
    with op.batch_alter_table("session_attestations") as batch:
        batch.add_column(sa.Column("status", sa.String(16), nullable=False, server_default="signed"))
        batch.add_column(sa.Column("payload", JSONType, nullable=True))
        batch.add_column(sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("next_attempt_at_ms", sa.BigInteger(), nullable=True))
        batch.add_column(sa.Column("last_error", sa.String(200), nullable=True))
        batch.add_column(sa.Column("signed_at_ms", sa.BigInteger(), nullable=True))
        batch.alter_column("attestation", existing_type=JSONType, nullable=True)
        batch.create_index("ix_session_attestations_status_next", ["status", "next_attempt_at_ms"])
    op.execute("UPDATE session_attestations SET signed_at_ms = issued_at_ms")


def downgrade() -> None:
    pending = op.get_bind().execute(
        sa.text("SELECT COUNT(*) FROM session_attestations WHERE attestation IS NULL")).scalar()
    if pending:
        raise RuntimeError(f"{pending} finished call(s) are still waiting to be signed. "
                           "Let the signer catch up before going back, or they would be lost.")
    with op.batch_alter_table("session_attestations") as batch:
        batch.drop_index("ix_session_attestations_status_next")
        batch.alter_column("attestation", existing_type=JSONType, nullable=False)
        for column in ("signed_at_ms", "last_error", "next_attempt_at_ms", "attempts", "payload", "status"):
            batch.drop_column(column)
    op.drop_table("attestation_keys")
