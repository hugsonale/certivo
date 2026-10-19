"""The published list of platform signing keys (ADR 0016).

Every key the platform has ever signed with stays on this list for good, marked `retired` once a
newer one takes over, so an attestation made years ago still verifies. Rotating a key is therefore:
create the new key, deploy with its new CERTIVO_ATTESTATION_KEY_ID (and KMS key), restart. The first
start with a new key adds it and retires the old one. Nothing is ever removed.
"""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.attestation import Signer
from app.models import AttestationKey

log = logging.getLogger("certivo.keys")


class KeyConflict(RuntimeError):
    """A key id that is already published is being used for a different key."""


def register_signing_key(db: Session, signer: Signer, now: int) -> AttestationKey:
    """Make sure the key this process signs with is published, and retire any older active key."""
    public_key = signer.public_key
    row = db.get(AttestationKey, signer.key_id)
    if row is not None and row.public_key != public_key:
        raise KeyConflict(
            f"The key id {signer.key_id!r} is already published with a different public key. "
            "Never reuse a key id: attestations signed by the old key would stop verifying. "
            "Choose a new CERTIVO_ATTESTATION_KEY_ID.")
    if row is None:
        row = AttestationKey(key_id=signer.key_id, alg="Ed25519", public_key=public_key,
                             status="active", created_at_ms=now)
        db.add(row)
        log.info("Published new attestation key %s", signer.key_id)
    elif row.status != "active":
        row.status, row.retired_at_ms = "active", None  # an older key is being brought back
    for other in db.scalars(select(AttestationKey).where(AttestationKey.status == "active",
                                                         AttestationKey.key_id != signer.key_id)):
        other.status, other.retired_at_ms = "retired", now
        log.info("Retired attestation key %s (still published, so old attestations verify)", other.key_id)
    db.commit()
    return row


def published_keys(db: Session) -> list[dict]:
    rows = db.scalars(select(AttestationKey).order_by(AttestationKey.created_at_ms, AttestationKey.key_id))
    return [{"key_id": r.key_id, "alg": r.alg, "public_key": r.public_key, "status": r.status,
             "created_at_ms": r.created_at_ms, "retired_at_ms": r.retired_at_ms} for r in rows]
