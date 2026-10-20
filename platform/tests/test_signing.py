"""P0-10: attestation service hardening.

The two drills the build guide asks for are here:
  * rotation drill: old attestations still verify, new ones use the new key;
  * signer outage drill: a call that ends while the signer is down is queued, then completed.
"""
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.attestation import (
    Signer,
    history_digest,
    history_root,
    verify_attestation,
    verify_with_published_keys,
)
from app.config import Settings
from app.crypto import ATTESTATION_DOMAIN, b64u_encode, canonical_json, sign_message
from app.keyregistry import KeyConflict
from app.main import create_app
from app.models import ScoreEvent, SessionAttestation
from app.sandbox import make_signed_packet
from app.services.sessions import retry_delay_ms, sign_pending
from app.signing import AwsKmsBackend, LocalKeyBackend, SignerUnavailable
from tests.conftest import SIGNING_KEY, T0, WEBHOOK_KEY

SECOND_KEY = b64u_encode(bytes(range(7, 39)))


# ------------------------------------------------------------------------------------- helpers


def post_packets(client, sess, sdk, device, count=3, participant="alice"):
    key, dev_id = device
    url = f"/internal/v1/sessions/continuous/{sess['id']}/score-events"
    for seq in range(count):
        start = T0 + seq * 1000
        pkt = make_signed_packet(key, sess["id"], dev_id, participant, seq, start, start + 1000, 900 - seq,
                                 ["consistent_motion"])
        assert client.post(url, json=pkt, headers=sdk).status_code == 200


def new_session(client, auth):
    r = client.post("/v1/sessions/continuous", headers=auth,
                    json={"use_case": "default_video_call", "participant_count": 1})
    assert r.status_code == 201, r.text
    body = r.json()
    return body, {"Authorization": f"Bearer {body['sdk_token']}"}


def keys_of(client):
    return client.get("/.well-known/certivo-keys").json()["keys"]


def second_app(db_url, clock, key=SECOND_KEY, key_id="att-test-2"):
    """A restart of the service with a different signing key, against the same database."""
    return create_app(Settings(database_url=db_url, attestation_signing_key=key, attestation_key_id=key_id,
                               webhook_secret_key=WEBHOOK_KEY, _env_file=None), clock=clock)


class FlakyBackend(LocalKeyBackend):
    """A signing service that can be switched off."""

    def __init__(self, key, key_id):
        super().__init__(key, key_id)
        self.up = True
        self.calls = 0

    def sign(self, message):
        self.calls += 1
        if not self.up:
            raise SignerUnavailable("signing service unreachable")
        return super().sign(message)


@pytest.fixture
def flaky(app):
    """The running app, signing through a backend we can switch off. Same key, so nothing else changes."""
    backend = FlakyBackend(Ed25519PrivateKey.from_private_bytes(bytes(range(100, 132))), "att-test-1")
    app.state.signer = Signer(backend)
    return backend


# --------------------------------------------------------------- the attestation itself (v2)


def test_a_new_attestation_is_version_2_and_verifies_against_the_published_keys(
        client, auth, device, session):
    sess, sdk = session
    post_packets(client, sess, sdk, device)
    end = client.post(f"/v1/sessions/continuous/{sess['id']}/end", headers=auth)
    assert end.status_code == 200 and end.json()["attestation_status"] == "signed"
    att = end.json()["attestation"]
    assert att["payload"]["v"] == 2 and att["payload"]["key_id"] == att["key_id"] == "att-test-1"
    assert verify_with_published_keys(att, keys_of(client))
    att["payload"]["coverage"]["coverage_milli"] -= 1  # any edit breaks it
    assert not verify_with_published_keys(att, keys_of(client))


def test_the_attestation_covers_the_full_scored_history_as_a_fingerprint(
        client, auth, app, device, session):
    sess, sdk = session
    post_packets(client, sess, sdk, device, count=4)
    att = client.post(f"/v1/sessions/continuous/{sess['id']}/end", headers=auth).json()["attestation"]
    payload = att["payload"]
    person = payload["participants"][0]
    assert person["outcome_counts"] == {"accept": 4, "fallback": 0, "reject": 0}
    with app.state.session_factory() as db:
        rows = list(db.scalars(select(ScoreEvent).where(ScoreEvent.session_id == sess["id"])
                               .order_by(ScoreEvent.seq)))
    assert person["history_sha256"] == history_digest(rows)  # reproducible from the stored packets
    assert payload["history"] == {"events_total": 4,
                                  "root_sha256": history_root({"alice": person["history_sha256"]})}


def test_the_history_fingerprint_changes_if_any_scored_interval_changes():
    def ev(**kw):
        base = dict(seq=0, interval_start_ms=1, interval_end_ms=2, confidence_milli=900,
                    outcome="accept", signature="sig")
        return SimpleNamespace(**{**base, **kw})

    base = history_digest([ev(), ev(seq=1)])
    assert history_digest([ev(), ev(seq=1)]) == base
    for change in ({"interval_start_ms": 9}, {"interval_end_ms": 9}, {"confidence_milli": 899},
                   {"outcome": "reject"}, {"signature": "other"}, {"seq": 5}):
        assert history_digest([ev(**change), ev(seq=1)]) != base
    assert history_digest([ev(seq=1), ev()]) != base  # order matters
    assert history_digest([ev()]) != base  # a missing interval matters


def test_attestations_signed_the_old_way_still_verify():
    key = Ed25519PrivateKey.generate()
    payload = {"v": 1, "type": "certivo_session_attestation", "session_id": "cs_old", "key_id": "att-old"}
    old = {"payload": payload, "signature": sign_message(key, ATTESTATION_DOMAIN, payload),
           "key_id": "att-old", "alg": "Ed25519"}
    public = b64u_encode(key.public_key().public_bytes(serialization.Encoding.Raw,
                                                       serialization.PublicFormat.Raw))
    assert verify_attestation(old, public)
    assert verify_with_published_keys(old, [{"key_id": "att-old", "alg": "Ed25519", "public_key": public}])


def test_the_attestation_can_be_fetched_later_and_not_before_the_call_ends(client, auth, device, session):
    sess, sdk = session
    url = f"/v1/sessions/continuous/{sess['id']}/attestation"
    early = client.get(url, headers=auth)
    assert early.status_code == 409 and early.json()["error"]["code"] == "attestation_not_ready"
    ended = client.post(f"/v1/sessions/continuous/{sess['id']}/end", headers=auth).json()
    later = client.get(url, headers=auth)
    assert later.status_code == 200 and later.json()["attestation"] == ended["attestation"]


# -------------------------------------------------------------------------- rotation drill


def test_rotation_drill_old_attestations_verify_and_new_ones_use_the_new_key(
        client, auth, device, session, db_url, clock):
    sess_a, sdk_a = session
    post_packets(client, sess_a, sdk_a, device)
    before = client.post(f"/v1/sessions/continuous/{sess_a['id']}/end", headers=auth).json()["attestation"]
    assert before["key_id"] == "att-test-1"
    assert [k["status"] for k in keys_of(client)] == ["active"]

    app2 = second_app(db_url, clock)  # the key is rotated and the service restarted
    try:
        client2 = TestClient(app2)
        sess_b, sdk_b = new_session(client2, auth)
        after = client2.post(f"/v1/sessions/continuous/{sess_b['id']}/end", headers=auth).json()["attestation"]
        assert after["key_id"] == "att-test-2" and after["payload"]["key_id"] == "att-test-2"

        published = keys_of(client2)
        assert [(k["key_id"], k["status"]) for k in published] == [("att-test-1", "retired"),
                                                                    ("att-test-2", "active")]
        assert published[0]["retired_at_ms"] is not None and published[1]["retired_at_ms"] is None

        assert verify_with_published_keys(before, published)  # the old attestation still verifies
        assert verify_with_published_keys(after, published)
        old_key = next(k["public_key"] for k in published if k["key_id"] == "att-test-1")
        new_key = next(k["public_key"] for k in published if k["key_id"] == "att-test-2")
        assert not verify_attestation(before, new_key) and not verify_attestation(after, old_key)
        fetched = client2.get(f"/v1/sessions/continuous/{sess_a['id']}/attestation", headers=auth)
        assert fetched.json()["attestation"] == before  # and the stored one is untouched
    finally:
        app2.state.engine.dispose()


def test_a_published_key_id_can_never_be_reused_for_a_different_key(app, db_url, clock):
    with pytest.raises(KeyConflict, match="already published with a different public key"):
        second_app(db_url, clock, key=SECOND_KEY, key_id="att-test-1")


def test_the_published_list_only_grows(client, db_url, clock):
    engines = []
    try:
        for n, seed in enumerate((SECOND_KEY, b64u_encode(bytes(range(50, 82)))), start=2):
            application = second_app(db_url, clock, key=seed, key_id=f"att-test-{n}")
            engines.append(application.state.engine)
        listed = keys_of(TestClient(application))
        assert [(k["key_id"], k["status"]) for k in listed] == [
            ("att-test-1", "retired"), ("att-test-2", "retired"), ("att-test-3", "active")]
    finally:
        for engine in engines:
            engine.dispose()


# ----------------------------------------------------------------------- signer outage drill


def end_url(sess):
    return f"/v1/sessions/continuous/{sess['id']}/end"


def test_signer_outage_drill_a_call_that_ends_is_queued_then_completed(
        client, auth, app, device, session, flaky, clock):
    sess, sdk = session
    post_packets(client, sess, sdk, device)
    flaky.up = False

    end = client.post(end_url(sess), headers=auth)  # the signer is down when the call ends
    assert end.status_code == 202  # accepted: the call has ended and its record exists
    body = end.json()
    assert body["status"] == "ended" and body["attestation_status"] == "pending"
    assert body["attestation"] is None and body["retry_after_s"] == 60
    assert body["coverage_summary"]["participants_observed"] == 1  # the coverage is already known
    assert client.post(end_url(sess), headers=auth).status_code == 202  # ending again changes nothing
    got = client.get(f"/v1/sessions/continuous/{sess['id']}/attestation", headers=auth)
    assert got.status_code == 202 and got.json()["attestation_status"] == "pending"

    issued_at = clock.t
    with app.state.session_factory() as db:
        rec = db.get(SessionAttestation, sess["id"])
        assert (rec.status, rec.attempts, rec.next_attempt_at_ms) == ("pending", 1, issued_at + 5_000)
        frozen = rec.payload

        clock.t = issued_at + 1_000  # too soon: nothing is attempted
        calls = flaky.calls
        assert sign_pending(db, app.state.signer, app.state.settings, clock.t) == {"signed": 0, "still_pending": 1}
        assert flaky.calls == calls

        clock.t = issued_at + 6_000  # due, but the signer is still down: backs off further
        assert sign_pending(db, app.state.signer, app.state.settings, clock.t)["signed"] == 0
        db.refresh(rec)
        assert (rec.attempts, rec.next_attempt_at_ms) == (2, clock.t + 10_000)

        flaky.up = True  # the signer comes back
        clock.t = rec.next_attempt_at_ms
        assert sign_pending(db, app.state.signer, app.state.settings, clock.t) == {"signed": 1, "still_pending": 0}
        db.refresh(rec)
        assert rec.status == "signed" and rec.signed_at_ms == clock.t and rec.payload is None

    done = client.get(f"/v1/sessions/continuous/{sess['id']}/attestation", headers=auth)
    assert done.status_code == 200 and done.json()["attestation_status"] == "signed"
    att = done.json()["attestation"]
    assert verify_with_published_keys(att, keys_of(client))
    assert att["payload"]["issued_at_ms"] == issued_at  # dated when the call ended, not when it was signed
    assert att["payload"]["coverage"] == frozen["coverage"]
    assert att["payload"]["participants"] == frozen["participants"]  # the record did not change while queued
    assert client.post(end_url(sess), headers=auth).json()["attestation"] == att


def test_retry_waits_grow_but_never_pass_the_cap():
    waits = [retry_delay_ms(n, 60) // 1000 for n in range(1, 8)]
    assert waits == [5, 10, 20, 40, 60, 60, 60]


def test_when_the_signer_is_down_one_failed_attempt_stops_the_pass(
        client, auth, app, device, flaky, clock):
    flaky.up = False
    for _ in range(3):
        sess, _ = new_session(client, auth)
        assert client.post(end_url(sess), headers=auth).status_code == 202
    clock.t += 10_000
    calls = flaky.calls
    with app.state.session_factory() as db:
        result = sign_pending(db, app.state.signer, app.state.settings, clock.t)
    assert result == {"signed": 0, "still_pending": 3}
    assert flaky.calls == calls + 1  # it did not hammer a service that is down


def test_an_attestation_queued_before_a_rotation_is_signed_by_the_new_key(
        client, auth, app, session, flaky, db_url, clock):
    sess, _ = session
    flaky.up = False
    assert client.post(end_url(sess), headers=auth).status_code == 202  # queued under att-test-1
    app2 = second_app(db_url, clock)  # rotated while it waited
    try:
        clock.t += 6_000
        with app2.state.session_factory() as db:
            assert sign_pending(db, app2.state.signer, app2.state.settings, clock.t)["signed"] == 1
        att = TestClient(app2).get(f"/v1/sessions/continuous/{sess['id']}/attestation", headers=auth).json()["attestation"]
        assert att["key_id"] == att["payload"]["key_id"] == "att-test-2"
        assert verify_with_published_keys(att, keys_of(TestClient(app2)))
    finally:
        app2.state.engine.dispose()


# -------------------------------------------------------------------- production key rules


def settings_for(**kw):
    return Settings(database_url="sqlite://", webhook_secret_key=WEBHOOK_KEY, _env_file=None, **kw)


def test_production_refuses_a_signing_key_from_the_environment(monkeypatch):
    for name in ("CERTIVO_ATTESTATION_SIGNING_KEY", "CERTIVO_ATTESTATION_SIGNER", "CERTIVO_ATTESTATION_KMS_KEY_ID"):
        monkeypatch.delenv(name, raising=False)  # this test is about what the settings object does, not the machine
    with pytest.raises(ValueError, match="must not be set in production"):
        settings_for(env="prod", attestation_signing_key=SIGNING_KEY, attestation_signer="aws_kms",
                     attestation_kms_key_id="alias/certivo")
    with pytest.raises(ValueError, match="managed key service"):
        settings_for(env="prod")  # the default, a key held by the application
    with pytest.raises(ValueError, match="KMS_KEY_ID is required"):
        settings_for(attestation_signer="aws_kms")
    ok = settings_for(env="prod", attestation_signer="aws_kms", attestation_kms_key_id="alias/certivo")
    assert ok.attestation_signer == "aws_kms" and ok.attestation_signing_key is None


# ------------------------------------------------------------ the managed key service adapter


class FakeKms:
    """Behaves like the AWS KMS API for an Ed25519 key: it enforces what AWS enforces (RAW messages of
    at most 4096 bytes, the ED25519_SHA_512 algorithm) and keeps the private key to itself."""

    def __init__(self, key_spec_ok=True):
        self._key = Ed25519PrivateKey.generate()
        self._rsa = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.key_spec_ok = key_spec_ok
        self.down = False
        self.sent = []

    def get_public_key(self, KeyId):
        if self.down:
            raise ConnectionError("kms unreachable")
        key = self._key if self.key_spec_ok else self._rsa
        return {"PublicKey": key.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)}

    def sign(self, KeyId, Message, MessageType, SigningAlgorithm):
        if self.down:
            raise ConnectionError("kms unreachable")
        assert MessageType == "RAW" and SigningAlgorithm == "ED25519_SHA_512"
        assert len(Message) <= 4096, "KMS refuses messages over 4096 bytes"
        self.sent.append(Message)
        return {"Signature": self._key.sign(Message)}


def test_the_managed_key_adapter_signs_through_the_service_and_verifies():
    kms = FakeKms()
    signer = Signer(AwsKmsBackend(kms, "alias/certivo", "att-kms-1"))
    payload = {"v": 2, "type": "certivo_session_attestation", "session_id": "cs_1", "key_id": "att-kms-1"}
    att = signer.sign_attestation(payload)
    assert verify_attestation(att, signer.public_key)
    assert att["key_id"] == "att-kms-1" and len(kms.sent) == 1


def test_a_large_attestation_still_fits_the_key_services_size_limit():
    kms = FakeKms()
    signer = Signer(AwsKmsBackend(kms, "alias/certivo", "att-kms-1"))
    payload = {"v": 2, "type": "certivo_session_attestation", "session_id": "cs_big", "key_id": "x",
               "gaps": [{"start_ms": n, "end_ms": n + 1, "reason": "connectivity"} for n in range(300)]}
    assert len(canonical_json(payload)) > 4096  # far too big to send whole
    att = signer.sign_attestation(payload)
    assert len(kms.sent[0]) < 100  # what is sent is a short fingerprint
    assert verify_attestation(att, signer.public_key)


def test_the_managed_key_adapter_reports_an_unreachable_service_as_unavailable():
    kms = FakeKms()
    signer = Signer(AwsKmsBackend(kms, "alias/certivo", "att-kms-1"))
    _ = signer.public_key
    kms.down = True
    with pytest.raises(SignerUnavailable, match="KMS signing failed"):
        signer.sign_attestation({"v": 2, "key_id": "x"})


def test_the_managed_key_adapter_rejects_a_key_of_the_wrong_type():
    backend = AwsKmsBackend(FakeKms(key_spec_ok=False), "alias/certivo", "att-kms-1")
    with pytest.raises(ValueError, match="ECC_NIST_EDWARDS25519"):
        backend.public_key()


def test_the_service_queues_attestations_when_the_key_service_is_down(
        client, auth, app, session, db_url, clock):
    """End to end with the managed key adapter in place of the local key."""
    kms = FakeKms()
    app.state.signer = Signer(AwsKmsBackend(kms, "alias/certivo", "att-test-1"))
    sess, _ = session
    kms.down = True
    assert client.post(end_url(sess), headers=auth).status_code == 202
    kms.down = False
    clock.t += 6_000
    with app.state.session_factory() as db:
        # (the registry holds the original key under this id, so the kms key must not be reused for it:
        # this test only checks the queue, so verify against the kms key directly)
        assert sign_pending(db, app.state.signer, app.state.settings, clock.t)["signed"] == 1
    att = client.get(f"/v1/sessions/continuous/{sess['id']}/attestation", headers=auth).json()["attestation"]
    assert verify_attestation(att, app.state.signer.public_key)


def test_restarting_in_development_without_a_signing_key_does_not_trip_the_key_registry(
        app, db_url, clock, monkeypatch):
    """On a developer's PC no key is configured, so every start makes a new throwaway key. Each one gets
    its own key id; otherwise the second start would be refused as an attempt to reuse the first id."""
    monkeypatch.delenv("CERTIVO_ATTESTATION_SIGNING_KEY", raising=False)  # "no key configured" must really be so
    engines = []
    try:
        ids = []
        for _ in range(2):
            application = create_app(Settings(database_url=db_url, attestation_key_id="att-dev-1",
                                              webhook_secret_key=WEBHOOK_KEY, _env_file=None), clock=clock)
            engines.append(application.state.engine)
            ids.append(application.state.signer.key_id)
        assert ids[0] != ids[1] and all(i.startswith("att-dev-1-ephemeral-") for i in ids)
        assert {k["key_id"] for k in keys_of(TestClient(application))} >= set(ids)
    finally:
        for engine in engines:
            engine.dispose()
