"""In-process token-bucket rate limiter.

LIMITATION, stated plainly: the counters live in this process's memory. With several app processes
or servers each one counts separately, so the real limit is (limit x number of processes). That is
acceptable for Phase 0; a shared (Redis) backend replaces it when Redis arrives with step P0-07.
"""
from __future__ import annotations

import math
import threading
from collections.abc import Callable
from dataclasses import dataclass

_WINDOW_MS = 60_000
_MAX_BUCKETS = 100_000
_EPSILON = 1e-9  # absorbs floating-point rounding so a bucket never waits a second too long


@dataclass(frozen=True)
class Decision:
    allowed: bool
    limit: int            # requests per minute
    remaining: int        # whole requests left right now
    retry_after_s: int    # 0 when allowed; otherwise seconds until one request is available
    reset_s: int          # seconds until the bucket is completely full again


class RateLimiter:
    def __init__(self, clock: Callable[[], int]):
        self._clock = clock
        self._buckets: dict[str, tuple[float, int]] = {}  # key -> (tokens, last_update_ms)
        self._lock = threading.Lock()
        self._operations = 0

    def check(self, key: str, limit_per_minute: int, *, consume: bool = True) -> Decision:
        """Ask for one request. With consume=False the bucket is only inspected, not charged."""
        now = self._clock()
        per_ms = limit_per_minute / _WINDOW_MS
        with self._lock:
            tokens, last = self._buckets.get(key, (float(limit_per_minute), now))
            tokens = min(float(limit_per_minute), tokens + max(0, now - last) * per_ms)
            allowed = tokens >= 1.0 - _EPSILON
            if allowed and consume:
                tokens -= 1.0
            self._buckets[key] = (tokens, now)
            self._operations += 1
            if self._operations % 1000 == 0 or len(self._buckets) > _MAX_BUCKETS:
                self._prune(now)
        per_s = per_ms * 1000
        return Decision(
            allowed=allowed,
            limit=limit_per_minute,
            remaining=int(tokens),
            retry_after_s=0 if allowed else max(1, math.ceil((1.0 - tokens) / per_s - _EPSILON)),
            reset_s=max(0, math.ceil((limit_per_minute - tokens) / per_s - _EPSILON)),
        )

    def _prune(self, now: int) -> None:
        """Forget buckets idle for a full window (they would be full again anyway), and cap memory."""
        self._buckets = {k: v for k, v in self._buckets.items() if now - v[1] < _WINDOW_MS}
        if len(self._buckets) > _MAX_BUCKETS:
            newest = sorted(self._buckets.items(), key=lambda kv: kv[1][1], reverse=True)
            self._buckets = dict(newest[: _MAX_BUCKETS // 2])
