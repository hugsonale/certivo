from __future__ import annotations

from collections.abc import Iterator

from fastapi import Request
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker


def make_engine(url: str) -> Engine:
    kwargs: dict = {}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
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
