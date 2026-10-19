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
    include_object,
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
        tables = {t for t in inspect(engine).get_table_names()
                  if include_object(None, t, "table", True, None)}  # not the daily partitions
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
            context = MigrationContext.configure(
                conn, opts={"compare_type": True, "include_object": include_object})
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


def test_migration_0004_keeps_score_events_and_their_ids(scratch_url):
    """Rows that existed before partitioning survive with the same IDs, get their session's start
    time as the partition key, and new rows carry on numbering after them. Going back also works."""
    import sqlalchemy as sa
    from sqlalchemy.dialects import postgresql

    cfg = alembic_config(scratch_url)
    command.upgrade(cfg, "0003")
    started = 1_760_000_000_000
    json_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
    engine = create_engine(scratch_url)
    row = dict(participant_ref="alice", device_id="dev", interval_start_ms=1, interval_end_ms=2,
               confidence_milli=900, model_version="m", explanation={"reason_codes": [], "signal_milli": {}},
               signature="s", outcome="accept", received_at_ms=started + 5)
    events = sa.table("continuous_score_events", sa.column("id", sa.Integer), sa.column("session_id", sa.String),
                      sa.column("participant_ref", sa.String), sa.column("seq", sa.Integer),
                      sa.column("device_id", sa.String), sa.column("interval_start_ms", sa.BigInteger),
                      sa.column("interval_end_ms", sa.BigInteger), sa.column("confidence_milli", sa.Integer),
                      sa.column("model_version", sa.String), sa.column("explanation", json_type),
                      sa.column("signature", sa.String), sa.column("outcome", sa.String),
                      sa.column("received_at_ms", sa.BigInteger))
    try:
        with engine.begin() as conn:
            conn.execute(sa.text("INSERT INTO partners (id, name, created_at_ms) VALUES ('p', 'P', 1)"))
            conn.execute(sa.text(
                "INSERT INTO continuous_sessions (id, partner_id, use_case, policy_id, policy_version, "
                "policy_config, participant_count, status, started_at_ms, sdk_token_hash, "
                "sdk_token_expires_at_ms) VALUES ('cs', 'p', 'u', 'pol', 1, '{}', 1, 'active', "
                f"{started}, 'h', {started + 1})"))
            for event_id, seq in ((10, 0), (11, 1), (12, 2)):
                conn.execute(events.insert().values(id=event_id, session_id="cs", seq=seq, **row))
        command.upgrade(cfg, "head")
        with engine.connect() as conn:
            kept = conn.execute(sa.text(
                "SELECT id, seq, session_started_at_ms FROM continuous_score_events ORDER BY id")).all()
            assert [(r.id, r.seq) for r in kept] == [(10, 0), (11, 1), (12, 2)]
            assert {r.session_started_at_ms for r in kept} == {started}
        with engine.begin() as conn:  # a new row gets the next number, not a clash with 10 to 12
            conn.execute(sa.text(
                "INSERT INTO continuous_score_events (session_id, participant_ref, seq, device_id, "
                "interval_start_ms, interval_end_ms, confidence_milli, model_version, explanation, "
                "signature, outcome, received_at_ms, session_started_at_ms) VALUES "
                f"('cs', 'alice', 3, 'dev', 1, 2, 900, 'm', '{{}}', 's', 'accept', {started}, {started})"))
        with engine.connect() as conn:
            assert conn.execute(sa.text("SELECT MAX(id) FROM continuous_score_events")).scalar() == 13
            if engine.dialect.name == "postgresql":
                partitioned = conn.execute(sa.text(
                    "SELECT COUNT(*) FROM pg_partitioned_table WHERE partrelid = "
                    "to_regclass('continuous_score_events')")).scalar()
                where = conn.execute(sa.text(
                    "SELECT DISTINCT tableoid::regclass::text FROM continuous_score_events")).scalars().all()
                assert partitioned == 1 and where == ["continuous_score_events_p20251009"]
                assert conn.execute(sa.text("SELECT to_regclass('continuous_score_events_default')")).scalar()
        command.downgrade(cfg, "0003")
        with engine.connect() as conn:
            assert conn.execute(sa.text("SELECT COUNT(*) FROM continuous_score_events")).scalar() == 4
            assert conn.execute(sa.text("SELECT MAX(id) FROM continuous_score_events")).scalar() == 13
    finally:
        engine.dispose()


def test_migration_0005_keeps_existing_attestations_and_protects_queued_ones(scratch_url):
    """Attestations that already exist count as signed and are untouched. Going back is refused while
    a finished call is still waiting to be signed, because it would be lost."""
    import json

    import sqlalchemy as sa

    cfg = alembic_config(scratch_url)
    command.upgrade(cfg, "0004")
    engine = create_engine(scratch_url)
    stored = {"payload": {"v": 1, "session_id": "cs"}, "signature": "sig", "key_id": "att-old", "alg": "Ed25519"}
    try:
        with engine.begin() as conn:
            conn.execute(sa.text("INSERT INTO partners (id, name, created_at_ms) VALUES ('p', 'P', 1)"))
            conn.execute(sa.text(
                "INSERT INTO continuous_sessions (id, partner_id, use_case, policy_id, policy_version, "
                "policy_config, participant_count, status, started_at_ms, sdk_token_hash, "
                "sdk_token_expires_at_ms) VALUES ('cs', 'p', 'u', 'pol', 1, '{}', 1, 'ended', 5, 'h', 6)"))
            conn.execute(sa.text("INSERT INTO session_attestations (session_id, attestation, issued_at_ms) "
                                 "VALUES ('cs', :a, 77)"), {"a": json.dumps(stored)})
        command.upgrade(cfg, "head")
        with engine.connect() as conn:
            row = conn.execute(sa.text(
                "SELECT status, attempts, signed_at_ms, attestation FROM session_attestations")).one()
            assert (row.status, row.attempts, row.signed_at_ms) == ("signed", 0, 77)
            assert (row.attestation if isinstance(row.attestation, dict) else json.loads(row.attestation)) == stored
        with engine.begin() as conn:  # a call that ended while the signer was down
            conn.execute(sa.text(
                "INSERT INTO continuous_sessions (id, partner_id, use_case, policy_id, policy_version, "
                "policy_config, participant_count, status, started_at_ms, sdk_token_hash, "
                "sdk_token_expires_at_ms) VALUES ('cs2', 'p', 'u', 'pol', 1, '{}', 1, 'ended', 5, 'h', 6)"))
            conn.execute(sa.text("INSERT INTO session_attestations (session_id, issued_at_ms, status, payload) "
                                 "VALUES ('cs2', 88, 'pending', '{}')"))
        with pytest.raises(RuntimeError, match="still waiting to be signed"):
            command.downgrade(cfg, "0004")
        with engine.begin() as conn:
            conn.execute(sa.text("DELETE FROM session_attestations WHERE session_id = 'cs2'"))
        command.downgrade(cfg, "0004")  # nothing waiting: going back is allowed
        with engine.connect() as conn:
            assert conn.execute(sa.text("SELECT COUNT(*) FROM session_attestations")).scalar() == 1
    finally:
        engine.dispose()
