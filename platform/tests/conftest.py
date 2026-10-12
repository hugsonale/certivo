import os

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text

from app.admin import create_partner
from app.config import Settings
from app.crypto import b64u_encode, public_key_b64u
from app.db import upgrade_to_head
from app.main import create_app
from app.models import Base

T0 = 1_760_000_000_000
SIGNING_KEY = b64u_encode(bytes(range(100, 132)))


class FakeClock:
    def __init__(self, t: int = T0):
        self.t = t

    def __call__(self) -> int:
        return self.t


@pytest.fixture(scope="session")
def db_url(tmp_path_factory):
    """Postgres when CERTIVO_TEST_DATABASE_URL is set (CI does this), otherwise a SQLite file."""
    url = os.environ.get("CERTIVO_TEST_DATABASE_URL")
    return url or f"sqlite:///{tmp_path_factory.mktemp('db') / 'test.db'}"


def clear_all_tables(url: str) -> None:
    """Empty every table between tests. The schema itself always comes from migrations."""
    engine = create_engine(url)
    try:
        inspector = inspect(engine)
        tables = [t for t in reversed(Base.metadata.sorted_tables) if inspector.has_table(t.name)]
        if not tables:
            return
        with engine.begin() as conn:
            if engine.dialect.name == "postgresql":
                names = ", ".join(f'"{t.name}"' for t in tables)
                conn.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))
            else:
                for table in tables:
                    conn.execute(table.delete())
    finally:
        engine.dispose()


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def app(db_url, clock):
    clear_all_tables(db_url)
    settings = Settings(
        database_url=db_url,
        attestation_signing_key=SIGNING_KEY,
        attestation_key_id="att-test-1",
        _env_file=None,
    )
    application = create_app(settings, clock=clock)  # env=dev, so it applies the migrations
    yield application
    application.state.engine.dispose()


@pytest.fixture
def make_app(db_url, clock):
    """Build an app with custom settings, e.g. make_app(rate_limit_key_per_minute=3, env="staging")."""
    created = []

    def factory(**overrides):
        clear_all_tables(db_url)
        upgrade_to_head(db_url)
        settings = Settings(database_url=db_url, attestation_signing_key=SIGNING_KEY,
                            attestation_key_id="att-test-1", _env_file=None, **overrides)
        application = create_app(settings, clock=clock)
        created.append(application)
        return application

    yield factory
    for application in created:
        application.state.engine.dispose()


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture
def partner_key(app):
    with app.state.session_factory() as db:
        partner, raw = create_partner(db, "Test Partner")
    return partner, raw


@pytest.fixture
def auth(partner_key):
    return {"Authorization": f"Bearer {partner_key[1]}"}


@pytest.fixture
def other_auth(app):
    with app.state.session_factory() as db:
        _, raw = create_partner(db, "Other Partner")
    return {"Authorization": f"Bearer {raw}"}


@pytest.fixture
def device(client, auth):
    key = Ed25519PrivateKey.generate()
    r = client.post("/v1/devices", json={"public_key": public_key_b64u(key)}, headers=auth)
    assert r.status_code == 201, r.text
    return key, r.json()["id"]


@pytest.fixture
def session(client, auth):
    r = client.post("/v1/sessions/continuous", headers=auth,
                    json={"use_case": "default_video_call", "participant_count": 2})
    assert r.status_code == 201, r.text
    body = r.json()
    return body, {"Authorization": f"Bearer {body['sdk_token']}"}
