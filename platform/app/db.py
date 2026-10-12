from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from fastapi import Request
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker


def make_engine(url: str, statement_timeout_ms: int | None = None) -> Engine:
    """statement_timeout_ms stops any single database statement running longer than that
    (Postgres) or waiting longer than that for a lock (SQLite)."""
    kwargs: dict = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False,
                                  "timeout": (statement_timeout_ms or 5_000) / 1000}
    elif url.startswith("postgresql") and statement_timeout_ms:
        kwargs["connect_args"] = {"options": f"-c statement_timeout={int(statement_timeout_ms)}"}
    return create_engine(url, future=True, **kwargs)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)


def get_db(request: Request) -> Iterator[Session]:
    with request.app.state.session_factory() as db:
        try:
            yield db
        except Exception:
            db.rollback()
            raise


# ---------------------------------------------------------------------------------------------
# Migrations (Alembic). The schema is defined by the files in platform/migrations/ and nothing
# else: no code path creates tables directly.
# ---------------------------------------------------------------------------------------------
PLATFORM_DIR = Path(__file__).resolve().parents[1]


class SchemaNotCurrent(RuntimeError):
    pass


def alembic_config(database_url: str) -> Config:
    cfg = Config(str(PLATFORM_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(PLATFORM_DIR / "migrations"))
    cfg.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    cfg.attributes["configure_logger"] = False  # do not reconfigure the app's logging
    return cfg


def upgrade_to_head(database_url: str) -> None:
    command.upgrade(alembic_config(database_url), "head")


def schema_revisions(engine: Engine) -> tuple[set[str], set[str]]:
    """Returns (revisions the database is at, revisions the code expects)."""
    head = set(ScriptDirectory.from_config(alembic_config(str(engine.url))).get_heads())
    with engine.connect() as conn:
        current = set(MigrationContext.configure(conn).get_current_heads())
    return current, head


def assert_schema_current(engine: Engine) -> None:
    current, head = schema_revisions(engine)
    if current != head:
        raise SchemaNotCurrent(
            f"The database schema is not up to date (database: {sorted(current) or 'empty'}, "
            f"expected: {sorted(head)}). Run 'alembic upgrade head' from the platform folder, "
            "then start the app again."
        )
