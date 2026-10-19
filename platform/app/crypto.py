"""Canonical JSON + Ed25519 signing for Certivo packets and attestations.

The canonical form is a *restricted profile* of JSON chosen so that a browser/iOS/Android
SDK can reproduce the exact same bytes without a JSON-canonicalization library:

* objects only contain keys matching ^[a-z0-9_]{1,64}$ (so key ordering is identical in
  every language), sorted ascending, no whitespace
* values are integers (|n| <= 2^53-1), printable-ASCII strings, arrays, or objects
* no floats, booleans or nulls (confidence is sent as an integer 0..1000 for this reason)
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

SCORE_DOMAIN = b"certivo.score.v1\n"
ATTESTATION_DOMAIN = b"certivo.attestation.v1\n"
ATTESTATION_DOMAIN_V2 = b"certivo.attestation.v2\n"

_KEY_RE = re.compile(r"^[a-z0-9_]{1,64}$")
_MAX_INT = 2**53 - 1


class CanonicalizationError(ValueError):
    pass


def _check(value: Any, path: str = "$") -> None:
    if value is None or isinstance(value, (bool, float)):
        raise CanonicalizationError(f"{path}: null, boolean and float values are not allowed")
    if isinstance(value, int):
        if abs(value) > _MAX_INT:
            raise CanonicalizationError(f"{path}: integer outside +/-(2^53-1)")
    elif isinstance(value, str):
        if not all(0x20 <= ord(c) <= 0x7E for c in value):
            raise CanonicalizationError(f"{path}: only printable ASCII strings are allowed")
    elif isinstance(value, list):
        for i, item in enumerate(value):
            _check(item, f"{path}[{i}]")
    elif isinstance(value, dict):
        for k, v in value.items():
            if not isinstance(k, str) or not _KEY_RE.match(k):
                raise CanonicalizationError(f"{path}: invalid key {k!r}")
            _check(v, f"{path}.{k}")
    else:
        raise CanonicalizationError(f"{path}: unsupported type {type(value).__name__}")


def canonical_json(value: Any) -> bytes:
    _check(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def b64u_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def b64u_decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def public_key_b64u(private_key: Ed25519PrivateKey) -> str:
    raw = private_key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    return b64u_encode(raw)


def attestation_message(payload: dict) -> bytes:
    """Exactly the bytes an attestation signature covers.

    v1 (Phase 0): the domain plus the whole canonical payload.
    v2: the domain plus the SHA-256 of the canonical payload. The signer is sent 55 bytes however
    large the attestation grows, which every managed key service accepts (AWS KMS, for one, signs at
    most 4096 bytes per call). The partner checks it the same way: hash the canonical payload, then
    verify an ordinary Ed25519 signature. The payload's own `v` says which form was used.
    """
    if payload.get("v") == 1:
        return ATTESTATION_DOMAIN + canonical_json(payload)
    return ATTESTATION_DOMAIN_V2 + hashlib.sha256(canonical_json(payload)).digest()


def sign_message(private_key: Ed25519PrivateKey, domain: bytes, value: Any) -> str:
    return b64u_encode(private_key.sign(domain + canonical_json(value)))


def verify_raw(public_key: str, message: bytes, signature: str) -> bool:
    try:
        Ed25519PublicKey.from_public_bytes(b64u_decode(public_key)).verify(
            b64u_decode(signature), message)
        return True
    except (InvalidSignature, ValueError):
        return False


def verify_message(public_key: str, domain: bytes, value: Any, signature: str) -> bool:
    """Returns False for any bad key/signature; raises CanonicalizationError for bad payload."""
    message = domain + canonical_json(value)
    try:
        Ed25519PublicKey.from_public_bytes(b64u_decode(public_key)).verify(
            b64u_decode(signature), message
        )
        return True
    except (InvalidSignature, ValueError):
        return False
