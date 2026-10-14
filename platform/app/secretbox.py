"""Encryption for secrets we must be able to read back (webhook signing secrets).

API keys are stored as one-way hashes because we only ever need to *check* them. A webhook signing
secret is different: we must *use* it to sign every delivery, so it cannot be a hash. It is encrypted
at rest instead, with a key that lives outside the database (a secrets manager in production).
"""
from __future__ import annotations

import base64
import hashlib
import logging

from cryptography.fernet import Fernet, InvalidToken

from app.config import Settings

log = logging.getLogger("certivo.secretbox")


class SecretBox:
    def __init__(self, key: str | bytes):
        self._fernet = Fernet(key)  # raises ValueError for a malformed key: fail at startup

    def encrypt(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode()).decode()

    def decrypt(self, token: str) -> str:
        try:
            return self._fernet.decrypt(token.encode()).decode()
        except InvalidToken as exc:
            raise ValueError("Could not decrypt: wrong CERTIVO_WEBHOOK_SECRET_KEY?") from exc


def load_secretbox(settings: Settings) -> SecretBox:
    if settings.webhook_secret_key:
        return SecretBox(settings.webhook_secret_key)
    if settings.env == "dev":
        # A fixed key so the API and the worker (separate processes) agree. It protects nothing:
        # anyone with this code can derive it. Dev only.
        log.warning("No CERTIVO_WEBHOOK_SECRET_KEY set: using an INSECURE fixed development key.")
        digest = hashlib.sha256(b"certivo-development-only-webhook-key").digest()
        return SecretBox(base64.urlsafe_b64encode(digest))
    raise RuntimeError("CERTIVO_WEBHOOK_SECRET_KEY is required when CERTIVO_ENV is not 'dev'. "
                       "Generate one with: python scripts/gen_webhook_key.py")
