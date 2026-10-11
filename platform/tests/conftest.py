import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from app.admin import create_partner
from app.config import Settings
from app.crypto import b64u_encode, public_key_b64u
from app.main import create_app

T0 = 1_760_000_000_000


class FakeClock:
    def __init__(self, t: int = T0):
        self.t = t

    def __call__(self) -> int:
        return self.t


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def app(tmp_path, clock):
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        attestation_signing_key=b64u_encode(bytes(range(100, 132))),
        attestation_key_id="att-test-1",
        _env_file=None,
    )
    return create_app(settings, clock=clock)


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
