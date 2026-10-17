"""Signing and checking webhook messages. This is both what Certivo does when it sends, and the
reference for what a partner's server should do when it receives (docs/spec/base/05-webhooks.md,
section 3). It depends on nothing but the Python standard library, so a partner can copy it.
"""
from __future__ import annotations

import hashlib
import hmac


def sign_body(secret: str, timestamp_ms: int, raw_body: bytes) -> str:
    """HMAC-SHA256, as lowercase hex, over '<timestamp_ms>.' followed by the exact body bytes."""
    message = str(timestamp_ms).encode() + b"." + raw_body
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def build_signature_header(secrets: list[str], timestamp_ms: int, raw_body: bytes) -> str:
    """'t=<ms>,v1=<hex>' with one v1 per secret. Two secrets are sent while one is being rotated."""
    parts = [f"t={timestamp_ms}"] + [f"v1={sign_body(s, timestamp_ms, raw_body)}" for s in secrets]
    return ",".join(parts)


def parse_signature_header(header: str) -> tuple[int, list[str]]:
    timestamp, signatures = None, []
    for part in header.split(","):
        name, _, value = part.strip().partition("=")
        if name == "t":
            timestamp = int(value)
        elif name == "v1":
            signatures.append(value)
    if timestamp is None or not signatures:
        raise ValueError("signature header needs a t= value and at least one v1= value")
    return timestamp, signatures


def verify_signature(secret: str, header: str, raw_body: bytes | str, now_ms: int,
                     tolerance_s: int = 300) -> bool:
    """True only if the message is recent AND was signed with this secret.

    Reject if the timestamp is more than `tolerance_s` seconds away from your own clock (this stops
    an old captured message being replayed), then compare in constant time against every v1 value.
    """
    body = raw_body.encode() if isinstance(raw_body, str) else raw_body
    try:
        timestamp, signatures = parse_signature_header(header)
    except ValueError:
        return False
    if abs(now_ms - timestamp) > tolerance_s * 1000:
        return False
    expected = sign_body(secret, timestamp, body)
    return any(hmac.compare_digest(expected, candidate) for candidate in signatures)


class ReplayGuard:
    """Remembers event IDs so the same message is not acted on twice.

    Certivo delivers each event AT LEAST once, so duplicates are normal. Keep IDs for longer than
    the longest retry period (about 22 hours with the default schedule); this default is 48 hours.

    IMPORTANT ORDER: ask `is_duplicate` first, handle the event, and call `record` ONLY AFTER you
    handled it successfully (just before answering 2xx). If you record the ID first and your handler
    then fails, our retry of that same event would be mistaken for a duplicate and lost.
    """

    def __init__(self, remember_for_s: int = 48 * 3600):
        self._remember_ms = remember_for_s * 1000
        self._seen: dict[str, int] = {}

    def _forget_old(self, now_ms: int) -> None:
        self._seen = {k: t for k, t in self._seen.items() if now_ms - t < self._remember_ms}

    def is_duplicate(self, event_id: str, now_ms: int) -> bool:
        self._forget_old(now_ms)
        return event_id in self._seen

    def record(self, event_id: str, now_ms: int) -> None:
        self._seen[event_id] = now_ms

    def first_time(self, event_id: str, now_ms: int) -> bool:
        """Check and record in one step. Only for handlers that cannot fail after this point."""
        if self.is_duplicate(event_id, now_ms):
            return False
        self.record(event_id, now_ms)
        return True
