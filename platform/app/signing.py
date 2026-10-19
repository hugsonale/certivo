"""The Cryptographic Service boundary: how the platform asks for a signature (P0-10, ADR 0016).

Everything that needs a signature goes through a `SigningBackend`: it can say which public key it
holds and sign a message with it. The private key stays behind that interface. In production the
backend is a managed key service whose private key never reaches this process; for development and
tests there is a local backend that holds a key in memory.

If a backend cannot be reached it raises `SignerUnavailable`, and callers queue the work and retry
instead of failing (System Design Document 7.2).
"""
from __future__ import annotations

import logging
from typing import Protocol

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from app.config import Settings
from app.crypto import b64u_decode

log = logging.getLogger("certivo.signing")


class SignerUnavailable(Exception):
    """The signing service could not be used right now. The request should be retried later."""


class SigningBackend(Protocol):
    key_id: str

    def public_key(self) -> bytes:
        """The raw 32-byte Ed25519 public key for this backend's key."""

    def sign(self, message: bytes) -> bytes:
        """An Ed25519 signature over `message`. Raises SignerUnavailable if it cannot be done now."""


class LocalKeyBackend:
    """A key held in this process's memory. Development and tests only: production refuses it."""

    def __init__(self, private_key: Ed25519PrivateKey, key_id: str):
        self._key = private_key
        self.key_id = key_id

    def public_key(self) -> bytes:
        return self._key.public_key().public_bytes(serialization.Encoding.Raw,
                                                   serialization.PublicFormat.Raw)

    def sign(self, message: bytes) -> bytes:
        return self._key.sign(message)


class AwsKmsBackend:
    """An Ed25519 key held in AWS KMS (key spec ECC_NIST_EDWARDS25519). The private key never leaves
    KMS: we send a short message and get a signature back. `client` is a boto3 KMS client."""

    def __init__(self, client, kms_key_id: str, key_id: str):
        self._client = client
        self._kms_key_id = kms_key_id
        self.key_id = key_id
        self._public: bytes | None = None

    def public_key(self) -> bytes:
        if self._public is None:
            try:
                der = self._client.get_public_key(KeyId=self._kms_key_id)["PublicKey"]
            except Exception as exc:
                raise SignerUnavailable(f"could not read the public key from KMS ({type(exc).__name__})") from exc
            key = serialization.load_der_public_key(der)
            if not isinstance(key, Ed25519PublicKey):
                raise ValueError("The KMS key is not an Ed25519 key. Create it with key spec "
                                 "ECC_NIST_EDWARDS25519 and key usage SIGN_VERIFY.")
            self._public = key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        return self._public

    def sign(self, message: bytes) -> bytes:
        try:
            reply = self._client.sign(KeyId=self._kms_key_id, Message=message, MessageType="RAW",
                                      SigningAlgorithm="ED25519_SHA_512")
            return reply["Signature"]
        except Exception as exc:
            log.error("KMS signing failed: %s", type(exc).__name__)
            raise SignerUnavailable(f"KMS signing failed ({type(exc).__name__})") from exc


def build_backend(settings: Settings) -> SigningBackend:
    if settings.attestation_signer == "aws_kms":
        try:
            import boto3  # imported only when AWS KMS is chosen, so other setups do not need it
        except ImportError as exc:
            raise RuntimeError("CERTIVO_ATTESTATION_SIGNER=aws_kms needs the boto3 package. "
                               "Add it to requirements.txt and rebuild.") from exc
        client = boto3.client("kms", region_name=settings.attestation_kms_region)
        return AwsKmsBackend(client, settings.attestation_kms_key_id or "", settings.attestation_key_id)
    if settings.attestation_signing_key:
        key = Ed25519PrivateKey.from_private_bytes(b64u_decode(settings.attestation_signing_key))
        return LocalKeyBackend(key, settings.attestation_key_id)
    # No key configured (development only): make a new one for this run. It needs a name of its own,
    # because a key id can never be reused for a different key (app/keyregistry.py).
    key = Ed25519PrivateKey.generate()
    backend = LocalKeyBackend(key, settings.attestation_key_id)
    backend.key_id = f"{settings.attestation_key_id}-ephemeral-{backend.public_key().hex()[:8]}"
    log.warning("No signing key configured: using a throwaway key %s (dev only). Attestations signed "
                "with it cannot be checked after the next restart; set CERTIVO_ATTESTATION_SIGNING_KEY "
                "(python scripts/gen_signing_key.py) to keep one.", backend.key_id)
    return backend
