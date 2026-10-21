"""Implausible-pattern detection (Technical Requirements Document 9.4, ADR 0018).

A device that fakes or replays scores tends to produce a pattern that a genuine device does not. This
module looks at one participant's latest scores and raises FLAGS: internal security signals, separate from a
low-confidence result. In Phase 0 a flag is only a flag. It never changes a decision, never rejects a packet
and is never shown to the partner.

Four patterns, each judged over the participant's latest `window` intervals (30 seconds of a real call):

  flat_maximum_confidence  every score is at or above the "maximum" line and they barely move
  impossible_score_jumps   several enormous swings between neighbouring intervals (a face cannot appear
                           and vanish again and again, second after second)
  faster_than_real_time    the packets arrived much faster than the time they claim to cover (a replay)
  zero_timing_jitter       packets arrived exactly the same number of milliseconds apart, every time

The numbers are PLACEHOLDERS to be tuned on real device data (P0-33 to P0-40). The timing patterns are only
judged on packets sent live. Packets uploaded in a batch after an outage legitimately arrive in a burst
(ADR 0014), so they are never counted as timing evidence.
"""
from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ContinuousSession, SecurityFlag

log = logging.getLogger("certivo.security")

FLAG_TYPES = ("flat_maximum_confidence", "impossible_score_jumps", "faster_than_real_time", "zero_timing_jitter")


@dataclass(frozen=True)
class AnomalyThresholds:
    window: int = 30                 # intervals examined; nothing is judged on fewer
    check_every: int = 10            # on the live path, examine every 10th packet once the window is full
    flat_floor_milli: int = 990      # "maximum confidence": every score at or above this
    flat_spread_milli: int = 5       # and highest minus lowest at most this
    jump_milli: int = 900            # a "jump": neighbouring scores differ by at least this
    jump_count: int = 3              # this many jumps inside the window is implausible
    fast_ratio_permille: int = 250   # arrivals spanning under 25% of the claimed time
    jitter_tolerance_ms: int = 1     # gaps all within this many ms of each other


DEFAULTS = AnomalyThresholds()


def detect(rows: Sequence, thresholds: AnomalyThresholds = DEFAULTS) -> list[tuple[str, dict]]:
    """The flags a participant's latest scores deserve, as (flag type, small facts). `rows` are that
    participant's score events, oldest first, with seq, confidence_milli, interval_start_ms,
    interval_end_ms, received_at_ms and received_via. A pure calculation: no database, no clock."""
    th = thresholds
    rows = list(rows)[-th.window:]
    if len(rows) < th.window:
        return []
    found: list[tuple[str, dict]] = []
    scores = [r.confidence_milli for r in rows]

    low, high = min(scores), max(scores)
    if low >= th.flat_floor_milli and high - low <= th.flat_spread_milli:
        found.append(("flat_maximum_confidence", {"intervals": len(rows), "min_milli": low, "max_milli": high}))

    jumps = sum(1 for a, b in zip(scores, scores[1:], strict=False) if abs(b - a) >= th.jump_milli)
    if jumps >= th.jump_count:
        found.append(("impossible_score_jumps", {"intervals": len(rows), "jumps": jumps,
                                                 "jump_milli": th.jump_milli}))

    contiguous = rows[-1].seq - rows[0].seq == len(rows) - 1  # a missing packet would distort the gaps
    if contiguous and all(r.received_via == "live" for r in rows):
        arrivals = [r.received_at_ms for r in rows]
        gaps = [b - a for a, b in zip(arrivals, arrivals[1:], strict=False)]
        claimed = sum(r.interval_end_ms - r.interval_start_ms for r in rows[1:])
        span = arrivals[-1] - arrivals[0]
        if claimed > 0 and span * 1000 < claimed * th.fast_ratio_permille:
            found.append(("faster_than_real_time", {"intervals": len(rows), "arrival_span_ms": span,
                                                    "claimed_ms": claimed}))
        if max(gaps) - min(gaps) <= th.jitter_tolerance_ms:
            found.append(("zero_timing_jitter", {"intervals": len(rows), "gap_ms": min(gaps)}))
    return found


def record_flags(db: Session, session: ContinuousSession, participant_ref: str, device_id: str,
                 rows_oldest_first: Sequence, now: int,
                 thresholds: AnomalyThresholds = DEFAULTS) -> list[str]:
    """Add a flag for each pattern found that this participant has not already been flagged for in this
    session. Returns the new flag types. Flags are raised once, not on every later packet."""
    found = detect(rows_oldest_first, thresholds)
    if not found:
        return []
    already = set(db.scalars(select(SecurityFlag.flag_type).where(
        SecurityFlag.session_id == session.id, SecurityFlag.participant_ref == participant_ref)))
    raised = []
    for flag_type, detail in found:
        if flag_type in already:
            continue
        db.add(SecurityFlag(
            session_id=session.id, partner_id=session.partner_id, participant_ref=participant_ref,
            device_id=device_id, flag_type=flag_type, detail=detail, first_seq=rows_oldest_first[-thresholds.window].seq,
            last_seq=rows_oldest_first[-1].seq, raised_at_ms=now))
        raised.append(flag_type)
        log.warning("security_flag type=%s session=%s participant=%s device=%s detail=%s",
                    flag_type, session.id, participant_ref, device_id, detail)
    return raised
