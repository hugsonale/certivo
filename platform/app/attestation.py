"""Platform signer + session-length attestation (BUILD_SPEC_0 section 8)."""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.config import Settings
from app.crypto import (
    ATTESTATION_DOMAIN,
    b64u_decode,
    canonical_json,
    public_key_b64u,
    sign_message,
    verify_message,
)

log = logging.getLogger("certivo.attestation")
MAX_GAPS_LISTED = 100


@dataclass
class Signer:
    private_key: Ed25519PrivateKey
    key_id: str

    @property
    def public_key(self) -> str:
        return public_key_b64u(self.private_key)

    def sign_attestation(self, payload: dict) -> dict:
        return {
            "payload": payload,
            "signature": sign_message(self.private_key, ATTESTATION_DOMAIN, payload),
            "key_id": self.key_id,
            "alg": "Ed25519",
        }


def load_signer(settings: Settings) -> Signer:
    if settings.attestation_signing_key:
        key = Ed25519PrivateKey.from_private_bytes(b64u_decode(settings.attestation_signing_key))
    elif settings.env == "prod":
        raise RuntimeError("CERTIVO_ATTESTATION_SIGNING_KEY is required when CERTIVO_ENV=prod")
    else:
        log.warning("No signing key configured: using an EPHEMERAL key (dev only). "
                    "Attestations will not verify after a restart.")
        key = Ed25519PrivateKey.generate()
    return Signer(key, settings.attestation_key_id)


def config_sha256(config: dict) -> str:
    return hashlib.sha256(canonical_json(config)).hexdigest()


def verify_attestation(attestation: dict, public_key: str) -> bool:
    """What a partner does: verify signature over the domain-separated canonical payload."""
    return verify_message(public_key, ATTESTATION_DOMAIN, attestation["payload"],
                          attestation["signature"])
