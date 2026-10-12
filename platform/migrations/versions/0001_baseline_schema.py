"""baseline schema

The first schema, matching app/models.py as of Build Spec 0. Drafted with autogenerate against an
empty Postgres database and reviewed by hand. Works on Postgres and SQLite.

Revision ID: 0001
Revises: 
Create Date: 2026-10-10

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0001'
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('partners',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('created_at_ms', sa.BigInteger(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_partners'))
    )
    op.create_table('api_keys',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('partner_id', sa.String(length=64), nullable=False),
    sa.Column('key_hash', sa.String(length=64), nullable=False),
    sa.Column('key_prefix', sa.String(length=16), nullable=False),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.Column('created_at_ms', sa.BigInteger(), nullable=False),
    sa.ForeignKeyConstraint(['partner_id'], ['partners.id'], name=op.f('fk_api_keys_partner_id_partners')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_api_keys')),
    sa.UniqueConstraint('key_hash', name=op.f('uq_api_keys_key_hash'))
    )
    op.create_index(op.f('ix_api_keys_partner_id'), 'api_keys', ['partner_id'], unique=False)
    op.create_table('continuous_sessions',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('partner_id', sa.String(length=64), nullable=False),
    sa.Column('use_case', sa.String(length=100), nullable=False),
    sa.Column('policy_id', sa.String(length=64), nullable=False),
    sa.Column('policy_version', sa.Integer(), nullable=False),
    sa.Column('policy_config', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('call_session_reference', sa.String(length=128), nullable=True),
    sa.Column('participant_count', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('started_at_ms', sa.BigInteger(), nullable=False),
    sa.Column('ended_at_ms', sa.BigInteger(), nullable=True),
    sa.Column('sdk_token_hash', sa.String(length=64), nullable=False),
    sa.ForeignKeyConstraint(['partner_id'], ['partners.id'], name=op.f('fk_continuous_sessions_partner_id_partners')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_continuous_sessions'))
    )
    op.create_index(op.f('ix_continuous_sessions_partner_id'), 'continuous_sessions', ['partner_id'], unique=False)
    op.create_table('devices',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('partner_id', sa.String(length=64), nullable=False),
    sa.Column('public_key', sa.String(length=64), nullable=False),
    sa.Column('trust_tier', sa.String(length=32), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('created_at_ms', sa.BigInteger(), nullable=False),
    sa.ForeignKeyConstraint(['partner_id'], ['partners.id'], name=op.f('fk_devices_partner_id_partners')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_devices'))
    )
    op.create_index(op.f('ix_devices_partner_id'), 'devices', ['partner_id'], unique=False)
    op.create_table('policies',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('partner_id', sa.String(length=64), nullable=True),
    sa.Column('use_case', sa.String(length=100), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('config', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('created_at_ms', sa.BigInteger(), nullable=False),
    sa.ForeignKeyConstraint(['partner_id'], ['partners.id'], name=op.f('fk_policies_partner_id_partners')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_policies')),
    sa.UniqueConstraint('partner_id', 'use_case', 'version', name='uq_policies_partner_use_case_version')
    )
    op.create_index('uq_policies_global_use_case_version', 'policies', ['use_case', 'version'], unique=True, postgresql_where=sa.text('partner_id IS NULL'), sqlite_where=sa.text('partner_id IS NULL'))
    op.create_table('webhook_outbox',
    sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
    sa.Column('partner_id', sa.String(length=64), nullable=False),
    sa.Column('event_type', sa.String(length=64), nullable=False),
    sa.Column('payload', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('created_at_ms', sa.BigInteger(), nullable=False),
    sa.Column('delivered_at_ms', sa.BigInteger(), nullable=True),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['partner_id'], ['partners.id'], name=op.f('fk_webhook_outbox_partner_id_partners')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_webhook_outbox'))
    )
    op.create_index(op.f('ix_webhook_outbox_partner_id'), 'webhook_outbox', ['partner_id'], unique=False)
    op.create_table('continuous_score_events',
    sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
    sa.Column('session_id', sa.String(length=64), nullable=False),
    sa.Column('participant_ref', sa.String(length=64), nullable=False),
    sa.Column('seq', sa.Integer(), nullable=False),
    sa.Column('device_id', sa.String(length=64), nullable=False),
    sa.Column('interval_start_ms', sa.BigInteger(), nullable=False),
    sa.Column('interval_end_ms', sa.BigInteger(), nullable=False),
    sa.Column('confidence_milli', sa.Integer(), nullable=False),
    sa.Column('model_version', sa.String(length=64), nullable=False),
    sa.Column('explanation', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('signature', sa.String(length=100), nullable=False),
    sa.Column('outcome', sa.String(length=16), nullable=False),
    sa.Column('received_at_ms', sa.BigInteger(), nullable=False),
    sa.ForeignKeyConstraint(['session_id'], ['continuous_sessions.id'], name=op.f('fk_continuous_score_events_session_id_continuous_sessions')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_continuous_score_events')),
    sa.UniqueConstraint('session_id', 'participant_ref', 'seq', name='uq_score_events_session_participant_seq')
    )
    op.create_table('coverage_gaps',
    sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
    sa.Column('session_id', sa.String(length=64), nullable=False),
    sa.Column('start_ms', sa.BigInteger(), nullable=False),
    sa.Column('end_ms', sa.BigInteger(), nullable=True),
    sa.Column('reason', sa.String(length=32), nullable=False),
    sa.ForeignKeyConstraint(['session_id'], ['continuous_sessions.id'], name=op.f('fk_coverage_gaps_session_id_continuous_sessions')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_coverage_gaps'))
    )
    op.create_index(op.f('ix_coverage_gaps_session_id'), 'coverage_gaps', ['session_id'], unique=False)
    op.create_table('session_attestations',
    sa.Column('session_id', sa.String(length=64), nullable=False),
    sa.Column('attestation', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('issued_at_ms', sa.BigInteger(), nullable=False),
    sa.ForeignKeyConstraint(['session_id'], ['continuous_sessions.id'], name=op.f('fk_session_attestations_session_id_continuous_sessions')),
    sa.PrimaryKeyConstraint('session_id', name=op.f('pk_session_attestations'))
    )


def downgrade() -> None:
    op.drop_table('session_attestations')
    op.drop_index(op.f('ix_coverage_gaps_session_id'), table_name='coverage_gaps')
    op.drop_table('coverage_gaps')
    op.drop_table('continuous_score_events')
    op.drop_index(op.f('ix_webhook_outbox_partner_id'), table_name='webhook_outbox')
    op.drop_table('webhook_outbox')
    op.drop_index('uq_policies_global_use_case_version', table_name='policies', postgresql_where=sa.text('partner_id IS NULL'), sqlite_where=sa.text('partner_id IS NULL'))
    op.drop_table('policies')
    op.drop_index(op.f('ix_devices_partner_id'), table_name='devices')
    op.drop_table('devices')
    op.drop_index(op.f('ix_continuous_sessions_partner_id'), table_name='continuous_sessions')
    op.drop_table('continuous_sessions')
    op.drop_index(op.f('ix_api_keys_partner_id'), table_name='api_keys')
    op.drop_table('api_keys')
    op.drop_table('partners')
