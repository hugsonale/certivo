"""webhook endpoints, deliveries and attempts

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-12

Adds what webhook delivery (build step P0-07) needs:
  * webhook_endpoints: the URLs partners register, with their (encrypted) signing secrets;
  * webhook_deliveries: one event headed for one endpoint, with its retry state;
  * webhook_attempts: the delivery log, one row per try;
and reshapes webhook_outbox into the events table (public event ID, fan-out marker, optional target).

Rows already in webhook_outbox are kept. They get an event ID and are marked as already handled, so
old events are never suddenly sent to endpoints that did not exist when they happened. The two
columns the outbox no longer uses (delivered_at_ms, attempts) were never filled in by any code.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")
BIG_ID = sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def upgrade() -> None:
    # 1. endpoints
    op.create_table(
        "webhook_endpoints",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("partner_id", sa.String(length=64), nullable=False),
        sa.Column("url", sa.String(length=2048), nullable=False),
        sa.Column("event_types", JSON_TYPE, nullable=False),
        sa.Column("description", sa.String(length=200), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("secret_encrypted", sa.String(length=512), nullable=False),
        sa.Column("previous_secret_encrypted", sa.String(length=512), nullable=True),
        sa.Column("previous_secret_expires_at_ms", sa.BigInteger(), nullable=True),
        sa.Column("created_at_ms", sa.BigInteger(), nullable=False),
        sa.Column("deleted_at_ms", sa.BigInteger(), nullable=True),
        sa.ForeignKeyConstraint(["partner_id"], ["partners.id"],
                                name=op.f("fk_webhook_endpoints_partner_id_partners")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_webhook_endpoints")),
    )
    op.create_index(op.f("ix_webhook_endpoints_partner_id"), "webhook_endpoints", ["partner_id"],
                    unique=False)

    # 2. reshape the outbox: add columns empty, backfill existing rows, then tighten
    op.add_column("webhook_outbox", sa.Column("event_id", sa.String(length=64), nullable=True))
    op.add_column("webhook_outbox", sa.Column("fanned_out_at_ms", sa.BigInteger(), nullable=True))
    op.add_column("webhook_outbox", sa.Column("target_endpoint_id", sa.String(length=64),
                                              nullable=True))
    outbox = sa.table("webhook_outbox", sa.column("id", sa.BigInteger),
                      sa.column("event_id", sa.String), sa.column("created_at_ms", sa.BigInteger),
                      sa.column("fanned_out_at_ms", sa.BigInteger))
    op.execute(outbox.update().values(
        event_id=sa.literal("evt_legacy_") + sa.cast(outbox.c.id, sa.String),
        fanned_out_at_ms=outbox.c.created_at_ms))  # already handled: never re-sent
    with op.batch_alter_table("webhook_outbox") as batch:
        batch.alter_column("event_id", existing_type=sa.String(length=64), nullable=False)
        batch.create_unique_constraint(op.f("uq_webhook_outbox_event_id"), ["event_id"])
        batch.create_foreign_key(op.f("fk_webhook_outbox_target_endpoint_id_webhook_endpoints"),
                                 "webhook_endpoints", ["target_endpoint_id"], ["id"])
        batch.create_index("ix_webhook_outbox_fanned_out_at_ms", ["fanned_out_at_ms"], unique=False)
        batch.drop_column("delivered_at_ms")
        batch.drop_column("attempts")

    # 3. deliveries
    op.create_table(
        "webhook_deliveries",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("outbox_id", BIG_ID, nullable=False),
        sa.Column("endpoint_id", sa.String(length=64), nullable=False),
        sa.Column("partner_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("failures_in_round", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at_ms", sa.BigInteger(), nullable=False),
        sa.Column("locked_until_ms", sa.BigInteger(), nullable=True),
        sa.Column("claim_token", sa.String(length=32), nullable=True),
        sa.Column("last_status_code", sa.Integer(), nullable=True),
        sa.Column("last_error", sa.String(length=40), nullable=True),
        sa.Column("created_at_ms", sa.BigInteger(), nullable=False),
        sa.Column("delivered_at_ms", sa.BigInteger(), nullable=True),
        sa.ForeignKeyConstraint(["endpoint_id"], ["webhook_endpoints.id"],
                                name=op.f("fk_webhook_deliveries_endpoint_id_webhook_endpoints")),
        sa.ForeignKeyConstraint(["outbox_id"], ["webhook_outbox.id"],
                                name=op.f("fk_webhook_deliveries_outbox_id_webhook_outbox")),
        sa.ForeignKeyConstraint(["partner_id"], ["partners.id"],
                                name=op.f("fk_webhook_deliveries_partner_id_partners")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_webhook_deliveries")),
        sa.UniqueConstraint("outbox_id", "endpoint_id", name="uq_webhook_deliveries_outbox_endpoint"),
    )
    op.create_index("ix_webhook_deliveries_due", "webhook_deliveries",
                    ["status", "next_attempt_at_ms"], unique=False)
    op.create_index("ix_webhook_deliveries_partner_created", "webhook_deliveries",
                    ["partner_id", "created_at_ms"], unique=False)

    # 4. the delivery log
    op.create_table(
        "webhook_attempts",
        sa.Column("id", BIG_ID, autoincrement=True, nullable=False),
        sa.Column("delivery_id", sa.String(length=64), nullable=False),
        sa.Column("attempted_at_ms", sa.BigInteger(), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("error", sa.String(length=40), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["delivery_id"], ["webhook_deliveries.id"],
                                name=op.f("fk_webhook_attempts_delivery_id_webhook_deliveries")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_webhook_attempts")),
    )
    op.create_index(op.f("ix_webhook_attempts_delivery_id"), "webhook_attempts", ["delivery_id"],
                    unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_webhook_attempts_delivery_id"), table_name="webhook_attempts")
    op.drop_table("webhook_attempts")
    op.drop_index("ix_webhook_deliveries_partner_created", table_name="webhook_deliveries")
    op.drop_index("ix_webhook_deliveries_due", table_name="webhook_deliveries")
    op.drop_table("webhook_deliveries")
    with op.batch_alter_table("webhook_outbox") as batch:
        batch.add_column(sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("delivered_at_ms", sa.BigInteger(), nullable=True))
        batch.drop_index("ix_webhook_outbox_fanned_out_at_ms")
        batch.drop_constraint(op.f("fk_webhook_outbox_target_endpoint_id_webhook_endpoints"),
                              type_="foreignkey")
        batch.drop_constraint(op.f("uq_webhook_outbox_event_id"), type_="unique")
        batch.drop_column("target_endpoint_id")
        batch.drop_column("fanned_out_at_ms")
        batch.drop_column("event_id")
    op.drop_index(op.f("ix_webhook_endpoints_partner_id"), table_name="webhook_endpoints")
    op.drop_table("webhook_endpoints")
