"""api key scopes, sdk token expiry, device revocation

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-11

Adds the columns behind scoped API keys, expiring SDK tokens and device revocation (build step P0-06).
Rows that already exist are backfilled so nothing that worked before stops working:
  * existing API keys keep full access (every scope), as base/02 promises;
  * existing sessions get an SDK token expiry of six hours after they started.
The scope list is copied in here on purpose: a migration must keep meaning the same thing even if
app/scopes.py changes later.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ALL_SCOPES = [
    "sessions:write", "sessions:read", "devices:write", "devices:read",
    "policies:write", "policies:read", "webhooks:write", "webhooks:read",
    "consents:write", "consents:read", "audit:read", "analytics:read", "keys:admin",
]
LEGACY_TOKEN_TTL_MS = 6 * 60 * 60 * 1000
JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    # 1. add the new columns as nullable so existing rows are allowed
    op.add_column("api_keys", sa.Column("name", sa.String(length=100), nullable=True))
    op.add_column("api_keys", sa.Column("scopes", JSON_TYPE, nullable=True))
    op.add_column("api_keys", sa.Column("last_used_at_ms", sa.BigInteger(), nullable=True))
    op.add_column("api_keys", sa.Column("revoked_at_ms", sa.BigInteger(), nullable=True))
    op.add_column("continuous_sessions",
                  sa.Column("sdk_token_expires_at_ms", sa.BigInteger(), nullable=True))
    op.add_column("devices", sa.Column("revoked_at_ms", sa.BigInteger(), nullable=True))

    # 2. backfill existing rows
    api_keys = sa.table("api_keys", sa.column("name", sa.String), sa.column("scopes", JSON_TYPE))
    op.execute(api_keys.update().values(name="initial key", scopes=ALL_SCOPES))
    sessions = sa.table("continuous_sessions",
                        sa.column("sdk_token_expires_at_ms", sa.BigInteger),
                        sa.column("started_at_ms", sa.BigInteger))
    op.execute(sessions.update().values(
        sdk_token_expires_at_ms=sessions.c.started_at_ms + LEGACY_TOKEN_TTL_MS))

    # 3. now that every row has a value, make the columns required
    with op.batch_alter_table("api_keys") as batch:
        batch.alter_column("name", existing_type=sa.String(length=100), nullable=False)
        batch.alter_column("scopes", existing_type=JSON_TYPE, nullable=False)
    with op.batch_alter_table("continuous_sessions") as batch:
        batch.alter_column("sdk_token_expires_at_ms", existing_type=sa.BigInteger(), nullable=False)


def downgrade() -> None:
    with op.batch_alter_table("devices") as batch:
        batch.drop_column("revoked_at_ms")
    with op.batch_alter_table("continuous_sessions") as batch:
        batch.drop_column("sdk_token_expires_at_ms")
    with op.batch_alter_table("api_keys") as batch:
        batch.drop_column("revoked_at_ms")
        batch.drop_column("last_used_at_ms")
        batch.drop_column("scopes")
        batch.drop_column("name")
