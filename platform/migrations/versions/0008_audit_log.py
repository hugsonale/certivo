"""audit log: append-only record of key, policy and credential changes (P0-13, ADR 0019)

The table is created, then the database is told to refuse any UPDATE, DELETE or TRUNCATE on it.

Revision ID: 0008_audit_log
Revises: 0007
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0008_audit_log"
down_revision = "0007"  # the migration this one follows (filled in by apply_p013.py)
branch_labels = None
depends_on = None

_JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
_BIG_ID = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
_MESSAGE = "audit_events is append-only: records can never be changed or deleted"


def upgrade() -> None:
    op.create_table(
        "audit_events",
        sa.Column("id", _BIG_ID, primary_key=True, autoincrement=True),
        sa.Column("at_ms", sa.BigInteger(), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("partner_id", sa.String(64), nullable=True),
        sa.Column("actor_type", sa.String(16), nullable=False),
        sa.Column("actor_id", sa.String(64), nullable=True),
        sa.Column("request_id", sa.String(64), nullable=True),
        sa.Column("target_type", sa.String(32), nullable=False),
        sa.Column("target_id", sa.String(64), nullable=True),
        sa.Column("details", _JSON, nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_audit_events"),
    )
    op.create_index("ix_audit_events_at_ms", "audit_events", ["at_ms"])
    op.create_index("ix_audit_events_partner_at", "audit_events", ["partner_id", "at_ms"])
    op.create_index("ix_audit_events_target", "audit_events", ["target_type", "target_id"])

    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.execute(f"""
            CREATE FUNCTION audit_events_refuse_change() RETURNS trigger
            LANGUAGE plpgsql AS $$
            BEGIN
                RAISE EXCEPTION '{_MESSAGE}';
            END;
            $$
        """)
        op.execute("CREATE TRIGGER audit_events_no_update_delete BEFORE UPDATE OR DELETE ON audit_events "
                   "FOR EACH ROW EXECUTE FUNCTION audit_events_refuse_change()")
        op.execute("CREATE TRIGGER audit_events_no_truncate BEFORE TRUNCATE ON audit_events "
                   "FOR EACH STATEMENT EXECUTE FUNCTION audit_events_refuse_change()")
    elif dialect == "sqlite":
        for verb in ("UPDATE", "DELETE"):
            op.execute(f"CREATE TRIGGER audit_events_no_{verb.lower()} BEFORE {verb} ON audit_events "
                       f"BEGIN SELECT RAISE(ABORT, '{_MESSAGE}'); END")
    else:  # pragma: no cover - the platform supports Postgres and SQLite only
        raise RuntimeError(f"No append-only protection is defined for {dialect}")


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.execute("DROP TRIGGER audit_events_no_truncate ON audit_events")
        op.execute("DROP TRIGGER audit_events_no_update_delete ON audit_events")
        op.execute("DROP FUNCTION audit_events_refuse_change()")
    elif dialect == "sqlite":
        op.execute("DROP TRIGGER audit_events_no_update")
        op.execute("DROP TRIGGER audit_events_no_delete")
    op.drop_index("ix_audit_events_target", table_name="audit_events")
    op.drop_index("ix_audit_events_partner_at", table_name="audit_events")
    op.drop_index("ix_audit_events_at_ms", table_name="audit_events")
    op.drop_table("audit_events")
