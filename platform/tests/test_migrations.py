"""Migrations are the only way the schema is created. These tests prove they work and that
they match app/models.py. They use throw-away databases, so they never touch the shared test one."""
import json
import uuid

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

from app.config import Settings
from app.db import (
    SchemaNotCurrent,
    alembic_config,
    assert_schema_current,
    upgrade_to_head,
)
from app.main import create_app
from app.models import Base
from tests.conftest import SIGNING_KEY, WEBHOOK_KEY


@pytest.fixture
def scratch_url(tmp_path, db_url):
    """An empty database that only this test uses."""
    if db_url.startswith("sqlite"):
        yield f"sqlite:///{tmp_path / 'scratch.db'}"
        return
    base = make_url(db_url)
    name = f"certivo_mig_{uuid.uuid4().hex[:10]}"
    admin = create_engine(base.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    try:
        yield base.set(database=name).render_as_string(hide_password=False)
    finally:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
        admin.dispose()


def settings_for(url: str, **kw) -> Settings:
    return Settings(database_url=url, attestation_signing_key=SIGNING_KEY,
                    webhook_secret_key=WEBHOOK_KEY, _env_file=None, **kw)


def test_there_is_exactly_one_migration_head(scratch_url):
    heads = ScriptDirectory.from_config(alembic_config(scratch_url)).get_heads()
    assert len(heads) == 1, f"Migration history has branched: {heads}"


def test_fresh_database_builds_from_migrations_only(scratch_url):
    upgrade_to_head(scratch_url)
    engine = create_engine(scratch_url)
    try:
        tables = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()
    expected = {t.name for t in Base.metadata.sorted_tables} | {"alembic_version"}
    assert tables == expected


def test_models_and_migrations_agree(scratch_url):
    """The same check CI runs as `alembic check`: no model change without a migration."""
    upgrade_to_head(scratch_url)
    engine = create_engine(scratch_url)
    try:
        with engine.connect() as conn:
            context = MigrationContext.configure(conn, opts={"compare_type": True})
            diff = compare_metadata(context, Base.metadata)
    finally:
        engine.dispose()
    assert diff == [], f"app/models.py and the migrations disagree. Create a migration: {diff}"


def test_downgrade_then_upgrade_again(scratch_url):
    cfg = alembic_config(scratch_url)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")
    engine = create_engine(scratch_url)
    try:
        assert set(inspect(engine).get_table_names()) <= {"alembic_version"}
    finally:
        engine.dispose()
    command.upgrade(cfg, "head")  # and it still works afterwards


def test_dev_environment_applies_migrations_automatically(scratch_url):
    app = create_app(settings_for(scratch_url))  # env defaults to "dev"
    try:
        assert "continuous_sessions" in inspect(app.state.engine).get_table_names()
    finally:
        app.state.engine.dispose()


@pytest.mark.parametrize("auto_migrate", [True, False])
def test_other_environments_never_migrate_and_refuse_to_start(scratch_url, auto_migrate):
    settings = settings_for(scratch_url, env="staging", auto_migrate=auto_migrate)
    with pytest.raises(SchemaNotCurrent, match="alembic upgrade head"):
        create_app(settings)
    engine = create_engine(scratch_url)
    try:
        assert not inspect(engine).has_table("partners")  # the failed start created nothing
    finally:
        engine.dispose()


def test_other_environments_start_once_migrated(scratch_url):
    upgrade_to_head(scratch_url)
    app = create_app(settings_for(scratch_url, env="staging"))
    try:
        assert_schema_current(app.state.engine)
    finally:
        app.state.engine.dispose()


def test_migration_0002_keeps_existing_rows_working(scratch_url):
    """Data that existed before P0-06 must survive and keep its power: old keys keep every scope,
    old sessions get an SDK token expiry."""
    import sqlalchemy as sa
    from sqlalchemy.dialects import postgresql

    from app.scopes import ALL_SCOPES

    cfg = alembic_config(scratch_url)
    command.upgrade(cfg, "0001")
    json_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
    partners = sa.table("partners", sa.column("id", sa.String), sa.column("name", sa.String),
                        sa.column("created_at_ms", sa.BigInteger))
    api_keys = sa.table("api_keys", sa.column("id", sa.String), sa.column("partner_id", sa.String),
                        sa.column("key_hash", sa.String), sa.column("key_prefix", sa.String),
                        sa.column("active", sa.Boolean), sa.column("created_at_ms", sa.BigInteger))
    sessions = sa.table(
        "continuous_sessions", sa.column("id", sa.String), sa.column("partner_id", sa.String),
        sa.column("use_case", sa.String), sa.column("policy_id", sa.String),
        sa.column("policy_version", sa.Integer), sa.column("policy_config", json_type),
        sa.column("participant_count", sa.Integer), sa.column("status", sa.String),
        sa.column("started_at_ms", sa.BigInteger), sa.column("sdk_token_hash", sa.String))
    engine = create_engine(scratch_url)
    try:
        with engine.begin() as conn:
            conn.execute(partners.insert().values(id="ptn_old", name="Old", created_at_ms=1))
            conn.execute(api_keys.insert().values(id="key_old", partner_id="ptn_old",
                                                  key_hash="h" * 64, key_prefix="cvk_old", active=True,
                                                  created_at_ms=1))
            conn.execute(sessions.insert().values(
                id="cs_old", partner_id="ptn_old", use_case="u", policy_id="pol", policy_version=1,
                policy_config={"a": 1}, participant_count=1, status="active",
                started_at_ms=5_000, sdk_token_hash="t" * 64))
        command.upgrade(cfg, "head")
        with engine.connect() as conn:
            key = conn.execute(sa.text("select name, scopes from api_keys")).one()
            session = conn.execute(sa.text(
                "select started_at_ms, sdk_token_expires_at_ms from continuous_sessions")).one()
    finally:
        engine.dispose()
    scopes = key.scopes if isinstance(key.scopes, list) else json.loads(key.scopes)
    assert key.name == "initial key" and set(scopes) == set(ALL_SCOPES)
    assert session.sdk_token_expires_at_ms == session.started_at_ms + 6 * 60 * 60 * 1000
