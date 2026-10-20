"""The platform signer and session-length attestations (BUILD_SPEC_0 section 8, ADR 0016)."""
from __future__ import annotations

import hashlib
import logging
from collections.abc import Iterable

from app.config import Settings
from app.crypto import attestation_message, b64u_encode, canonical_json, verify_raw
from app.signing import LocalKeyBackend, SigningBackend, build_backend

log = logging.getLogger("certivo.attestation")
MAX_GAPS_LISTED = 100
ATTESTATION_VERSION = 2


class Signer:
    """What the rest of the platform holds: ask it to sign an attestation payload. It knows nothing
    about where the private key lives; that is the backend's business."""

    def __init__(self, backend: SigningBackend):
        self._backend = backend

    @property
    def key_id(self) -> str:
        return self._backend.key_id

    @property
    def public_key(self) -> str:
        return b64u_encode(self._backend.public_key())

    def sign_attestation(self, payload: dict) -> dict:
        # The payload always names the key that really signed it, even if the signing was queued
        # and the key was rotated in the meantime.
        payload = {**payload, "key_id": self.key_id}
        signature = self._backend.sign(attestation_message(payload))
        return {"payload": payload, "signature": b64u_encode(signature),
                "key_id": self.key_id, "alg": "Ed25519"}


def load_signer(settings: Settings) -> Signer:
    backend = build_backend(settings)
    if settings.env == "prod" and isinstance(backend, LocalKeyBackend):
        raise RuntimeError("Production must sign with a managed key service, never a key held by "
                           "the application (CERTIVO_ATTESTATION_SIGNER=aws_kms).")
    return Signer(backend)


def config_sha256(config: dict) -> str:
    return hashlib.sha256(canonical_json(config)).hexdigest()


def history_digest(events: Iterable) -> str:
    """SHA-256 over every scored interval of one participant, in order: seq, start, end, confidence,
    outcome and the device's own signature on that packet. The attestation keeps this fingerprint
    after the per-interval rows are deleted by retention: it proves, for as long as anyone holds the
    packets, exactly which history the attestation covers, without putting any of it in the record."""
    rows = [[e.seq, e.interval_start_ms, e.interval_end_ms, e.confidence_milli, e.outcome, e.signature]
            for e in events]
    return hashlib.sha256(canonical_json(rows)).hexdigest()


def history_root(digests_by_participant: dict[str, str]) -> str:
    return hashlib.sha256(canonical_json(
        [[ref, digest] for ref, digest in sorted(digests_by_participant.items())])).hexdigest()


def verify_attestation(attestation: dict, public_key: str) -> bool:
    """What a partner does: hash and verify the signature over the attestation's canonical payload."""
    return verify_raw(public_key, attestation_message(attestation["payload"]), attestation["signature"])


def verify_with_published_keys(attestation: dict, published_keys: list[dict]) -> bool:
    """Pick the key the attestation names from the published list (retired keys included) and verify."""
    key_id = attestation.get("key_id")
    if key_id != attestation["payload"].get("key_id"):
        return False
    for key in published_keys:
        if key["key_id"] == key_id and key.get("alg", "Ed25519") == attestation.get("alg", "Ed25519"):
            return verify_attestation(attestation, key["public_key"])
    return False
