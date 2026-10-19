from __future__ import annotations

import logging

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.attestation import (
    ATTESTATION_VERSION,
    MAX_GAPS_LISTED,
    Signer,
    config_sha256,
    history_digest,
    history_root,
)
from app.config import Settings
from app.crypto import SCORE_DOMAIN, CanonicalizationError, verify_message
from app.errors import ApiError
from app.models import (
    ContinuousSession,
    CoverageGap,
    Device,
    Partner,
    Policy,
    ScoreEvent,
    SessionAttestation,
    WebhookOutbox,
    new_id,
)
from app.policy import (
    effective_confidence,
    evaluate,
    is_model_supported,
    normalize_config,
    outcome_to_report,
)
from app.schemas import (
    BatchItemError,
    BatchItemOut,
    ScoreBatchOut,
    ScoreEventIn,
    ScoreEventOut,
    SessionStartIn,
)
from app.security import new_sdk_token, sha256_hex
from app.signing import SignerUnavailable

log = logging.getLogger("certivo.sessions")


def _emit(db: Session, partner_id: str, event_type: str, payload: dict, now: int) -> None:
    db.add(WebhookOutbox(event_id=new_id("evt"), partner_id=partner_id, event_type=event_type,
                         payload=payload, created_at_ms=now))


def start_session(db: Session, partner: Partner, req: SessionStartIn, now: int, ttl_ms: int):
    policy = db.scalar(
        select(Policy)
        .where(Policy.use_case == req.use_case,
               or_(Policy.partner_id == partner.id, Policy.partner_id.is_(None)))
        .order_by(Policy.partner_id.is_(None), Policy.version.desc())  # partner-specific first
        .limit(1)
    )
    if policy is None:
        raise ApiError(404, "policy_not_found",
                       f"No policy configured for use_case '{req.use_case}'")
    token = new_sdk_token()
    session = ContinuousSession(
        id=new_id("cs"), partner_id=partner.id, use_case=req.use_case,
        policy_id=policy.id, policy_version=policy.version, policy_config=dict(policy.config),
        call_session_reference=req.call_session_reference,
        participant_count=req.participant_count, status="active",
        started_at_ms=now, sdk_token_hash=sha256_hex(token),
        sdk_token_expires_at_ms=now + ttl_ms,
    )
    db.add(session)
    db.commit()
    return session, token


def _of_session(session: ContinuousSession):
    """Every score-event query names the session AND the day it started. The second condition is
    the partition key, so Postgres reads one daily partition instead of all of them."""
    return (ScoreEvent.session_id == session.id,
            ScoreEvent.session_started_at_ms == session.started_at_ms)


def event_lookup_stmt(session: ContinuousSession, participant_ref: str, seq: int):
    return select(ScoreEvent).where(*_of_session(session), ScoreEvent.participant_ref == participant_ref,
                                    ScoreEvent.seq == seq)


def recent_events_stmt(session: ContinuousSession, participant_ref: str, limit: int):
    return (select(ScoreEvent).where(*_of_session(session), ScoreEvent.participant_ref == participant_ref)
            .order_by(ScoreEvent.seq.desc()).limit(limit))


def session_events_stmt(session: ContinuousSession):
    return (select(ScoreEvent).where(*_of_session(session))
            .order_by(ScoreEvent.participant_ref, ScoreEvent.seq))


def participant_refs_stmt(session: ContinuousSession):
    return select(ScoreEvent.participant_ref).where(*_of_session(session)).distinct()


def event_count_stmt(session: ContinuousSession, participant_ref: str):
    return select(func.count()).select_from(ScoreEvent).where(
        *_of_session(session), ScoreEvent.participant_ref == participant_ref)


def _outcome_out(event: ScoreEvent, duplicate: bool) -> ScoreEventOut:
    return ScoreEventOut(accepted=True, seq=event.seq,
                         current_policy_outcome=event.outcome, duplicate=duplicate)


def _close_open_gap(db: Session, session: ContinuousSession, now: int) -> None:
    gap = db.scalar(select(CoverageGap).where(CoverageGap.session_id == session.id,
                                              CoverageGap.end_ms.is_(None)))
    if gap:
        gap.end_ms = now


def _ingest(db: Session, settings: Settings, session: ContinuousSession, req: ScoreEventIn,
            now: int) -> tuple[ScoreEventOut, ScoreEvent, ScoreEvent | None]:
    """Validate one packet and add it to the database session, WITHOUT committing.

    Every refusal is raised before anything is written, so a refused packet leaves no trace.
    Returns (result, the stored event, the participant's previous event or None).
    """
    if session.status == "ended":
        raise ApiError(409, "session_not_active", "Session has ended")

    # 1. Authenticate the packet: the device must be known, active, and the signature valid.
    device = db.get(Device, req.device_id)
    bad_sig = ApiError(401, "invalid_device_signature",
                       "device_signature does not validate against a known, active device key")
    if device is None or device.partner_id != session.partner_id or device.status != "active":
        raise bad_sig
    try:
        valid = verify_message(device.public_key, SCORE_DOMAIN,
                               req.signed_payload(session.id), req.device_signature)
    except CanonicalizationError as exc:
        raise ApiError(422, "non_canonical_payload", str(exc)) from exc
    if not valid:
        raise bad_sig
    # A score from a model version this policy lists as unsupported is refused, not scored (ML 2.5):
    # a known-defective on-device model must not be able to accept or reject anyone. Nothing is stored.
    if not is_model_supported(session.policy_config, req.model_version):
        raise ApiError(422, "model_version_unsupported",
                       f"This session's policy does not accept scores from model version "
                       f"{req.model_version!r}. Update the SDK to a supported version.")

    # 2. Sanity-check the (now authenticated) timing fields.
    span = req.interval_end_ms - req.interval_start_ms
    if span <= 0 or span > settings.max_interval_ms:
        raise ApiError(422, "invalid_interval",
                       f"interval must be 1..{settings.max_interval_ms} ms long")
    if req.interval_end_ms > now + settings.max_clock_skew_ms:
        raise ApiError(422, "timestamp_in_future", "interval_end_ms is ahead of server time")

    # 3. Idempotency / ordering per participant.
    ref = req.participant_reference
    existing = db.scalar(event_lookup_stmt(session, ref, req.seq))
    if existing:
        if existing.signature == req.device_signature:
            return _outcome_out(existing, duplicate=True), existing, None
        raise ApiError(409, "seq_conflict", "A different packet already used this seq")
    recent = list(db.scalars(recent_events_stmt(
        session, ref, max(session.policy_config["drop_consecutive"], 1))))
    last = recent[0] if recent else None
    if last and req.seq < last.seq:
        raise ApiError(409, "seq_out_of_order", "seq must increase per participant")
    if last and req.interval_end_ms < last.interval_end_ms:
        raise ApiError(409, "non_monotonic_interval", "interval_end_ms went backwards")

    # 4. A valid packet while paused implicitly resumes the session.
    if session.status == "paused":
        _close_open_gap(db, session, now)
        session.status = "active"

    config = normalize_config(session.policy_config)
    effective = effective_confidence(config, device.trust_tier, req.model_version, req.confidence_milli)
    prior = [e.effective_confidence_milli for e in reversed(recent)]
    outcome = evaluate(config, prior, effective)
    event = ScoreEvent(
        session_id=session.id, participant_ref=ref, seq=req.seq, device_id=device.id,
        interval_start_ms=req.interval_start_ms, interval_end_ms=req.interval_end_ms,
        confidence_milli=req.confidence_milli, effective_confidence_milli=effective,
        model_version=req.model_version, explanation=req.explanation.model_dump(),
        signature=req.device_signature, outcome=outcome, received_at_ms=now,
        session_started_at_ms=session.started_at_ms,
    )
    db.add(event)
    reported = outcome_to_report(config, last.outcome if last else None, outcome)
    if reported:  # FR-C.8: a drop is never silently ignored
        _emit(db, session.partner_id, "session.confidence_dropped", {
            "session_id": session.id, "participant_reference": ref, "seq": req.seq,
            "confidence_milli": req.confidence_milli, "outcome": reported,
            "occurred_at_ms": req.interval_end_ms,
        }, now)
    return _outcome_out(event, duplicate=False), event, last


def ingest_score_event(db: Session, settings: Settings, session: ContinuousSession,
                       req: ScoreEventIn, now: int) -> ScoreEventOut:
    out, _, _ = _ingest(db, settings, session, req, now)
    try:
        db.commit()
    except IntegrityError as exc:  # concurrent duplicate
        db.rollback()
        raise ApiError(409, "seq_conflict", "A packet with this seq was just recorded") from exc
    return out


def _already_disclosed(db: Session, session_id: str, start_ms: int, end_ms: int) -> bool:
    """True if one existing gap (for example an explicit pause) already covers this whole span."""
    return db.scalar(select(CoverageGap.id).where(
        CoverageGap.session_id == session_id, CoverageGap.start_ms <= start_ms,
        or_(CoverageGap.end_ms.is_(None), CoverageGap.end_ms >= end_ms)).limit(1)) is not None


def ingest_score_batch(db: Session, settings: Settings, session: ContinuousSession,
                       packets: list[ScoreEventIn], now: int) -> ScoreBatchOut:
    """Packets the SDK buffered during an outage, oldest first (docs/adr/0014).

    Each packet is checked on its own, exactly as a single packet is, so one bad packet is
    reported without losing the good ones. Everything that is accepted, and every coverage gap it
    reveals, is saved in one transaction: a crash can never leave the packets without their gap.
    """
    if session.status == "ended":
        raise ApiError(409, "session_not_active", "Session has ended")
    threshold = settings.gap_disclosure_threshold_ms
    results: list[BatchItemOut] = []
    newly_stored: list[ScoreEvent] = []
    holes: list[tuple[int, int]] = []
    try:
        for index, req in enumerate(packets):
            try:
                out, event, last = _ingest(db, settings, session, req, now)
            except ApiError as exc:
                results.append(BatchItemOut(index=index, accepted=False, seq=req.seq,
                                            error=BatchItemError(code=exc.code, message=exc.message)))
                continue
            results.append(BatchItemOut(
                index=index, accepted=True, seq=out.seq, duplicate=out.duplicate,
                current_policy_outcome=out.current_policy_outcome))
            if out.duplicate:
                continue
            newly_stored.append(event)
            if last is not None and event.interval_start_ms - last.interval_end_ms > threshold:
                holes.append((last.interval_end_ms, event.interval_start_ms))

        gaps: list[CoverageGap] = []
        for start, end in holes:  # packets that never arrived (the SDK's buffer overflowed)
            if not _already_disclosed(db, session.id, start, end):
                gaps.append(CoverageGap(session_id=session.id, start_ms=start, end_ms=end,
                                        reason="missing_packets"))
        late = [e for e in newly_stored if now - e.interval_end_ms > threshold]
        if late:  # packets that arrived, but long after the moment they describe
            start = min(e.interval_start_ms for e in late)
            if not _already_disclosed(db, session.id, start, now):
                gaps.append(CoverageGap(session_id=session.id, start_ms=start, end_ms=now,
                                        reason="delayed_upload"))
        db.add_all(gaps)
        db.commit()
    except IntegrityError as exc:  # a concurrent upload recorded the same seq; retry is safe
        db.rollback()
        raise ApiError(409, "seq_conflict", "A packet with this seq was just recorded") from exc

    return ScoreBatchOut(
        results=results,
        accepted_count=sum(1 for r in results if r.accepted and not r.duplicate),
        duplicate_count=sum(1 for r in results if r.duplicate),
        rejected_count=sum(1 for r in results if not r.accepted),
        gaps_recorded=len(gaps))


def _uncovered_ms(gaps: list[CoverageGap], started_ms: int, now: int) -> int:
    """Total time inside the session covered by at least one gap. Gaps can overlap (a pause that
    contains a late upload, say), and overlapping time is counted once."""
    spans = sorted((max(g.start_ms, started_ms), min(g.end_ms if g.end_ms is not None else now, now))
                   for g in gaps)
    total, current_end = 0, None
    for start, end in spans:
        if end <= start:
            continue
        if current_end is None or start > current_end:
            total += end - start
            current_end = end
        elif end > current_end:
            total += end - current_end
            current_end = end
    return total


def pause_session(db: Session, session: ContinuousSession, reason: str, now: int) -> None:
    if session.status == "ended":
        raise ApiError(409, "session_not_active", "Session has ended")
    if session.status == "paused":
        return
    session.status = "paused"
    db.add(CoverageGap(session_id=session.id, start_ms=now, reason=reason))
    _emit(db, session.partner_id, "session.paused",
          {"session_id": session.id, "reason": reason, "occurred_at_ms": now}, now)
    db.commit()


def resume_session(db: Session, session: ContinuousSession, now: int) -> None:
    if session.status == "ended":
        raise ApiError(409, "session_not_active", "Session has ended")
    if session.status == "paused":
        _close_open_gap(db, session, now)
        session.status = "active"
        db.commit()


def retry_delay_ms(attempts: int, max_wait_s: int) -> int:
    """Wait before signing attempt number `attempts + 1`: 5 s, 10 s, 20 s... never more than the cap."""
    return min(5 * 2 ** max(attempts - 1, 0), max_wait_s) * 1000


def _try_to_sign(rec: SessionAttestation, signer: Signer, now: int, max_wait_s: int) -> bool:
    """Sign a pending record. On success it becomes `signed`. If the signer is unreachable it stays
    queued, with the next attempt scheduled. Returns True if it was signed."""
    try:
        rec.attestation = signer.sign_attestation(rec.payload)
    except SignerUnavailable as exc:
        rec.attempts += 1
        rec.next_attempt_at_ms = now + retry_delay_ms(rec.attempts, max_wait_s)
        rec.last_error = str(exc)[:200]
        log.error("Attestation for %s is queued (attempt %d): %s", rec.session_id, rec.attempts, exc)
        return False
    rec.status, rec.signed_at_ms = "signed", now
    rec.payload, rec.next_attempt_at_ms, rec.last_error = None, None, None
    return True


def sign_pending(db: Session, signer: Signer, settings: Settings, now: int, limit: int = 100) -> dict:
    """Sign the attestations that were queued while the signer was unreachable. Stops at the first
    failure, because if the signer is down every later attempt would fail too."""
    due = list(db.scalars(select(SessionAttestation).where(
        SessionAttestation.status == "pending", SessionAttestation.next_attempt_at_ms <= now)
        .order_by(SessionAttestation.next_attempt_at_ms).limit(limit)))
    signed = 0
    for rec in due:
        if not _try_to_sign(rec, signer, now, settings.attestation_retry_max_wait_s):
            break
        signed += 1
    db.commit()
    waiting = db.scalar(select(func.count()).select_from(SessionAttestation)
                        .where(SessionAttestation.status == "pending")) or 0
    return {"signed": signed, "still_pending": waiting}


def end_session(db: Session, signer: Signer, settings: Settings, session: ContinuousSession,
                now: int) -> SessionAttestation:
    """End the call and produce its record. The record always exists once this returns: if the signer
    is unreachable the attestation is queued with its payload frozen and signed later (SDD 7.2)."""
    rec = db.get(SessionAttestation, session.id)
    if session.status == "ended" and rec:
        return rec

    _close_open_gap(db, session, now)
    session.status = "ended"
    session.ended_at_ms = now
    events = list(db.scalars(session_events_stmt(session)))
    gaps = list(db.scalars(select(CoverageGap).where(CoverageGap.session_id == session.id)
                           .order_by(CoverageGap.start_ms)))

    by_ref: dict[str, list[ScoreEvent]] = {}
    for e in events:
        by_ref.setdefault(e.participant_ref, []).append(e)
    participants, digests = [], {}
    for ref in sorted(by_ref):
        evs = by_ref[ref]
        drops, prev = 0, None
        counts = {"accept": 0, "fallback": 0, "reject": 0}
        for e in evs:
            if e.outcome == "reject" and prev != "reject":
                drops += 1
            prev = e.outcome
            counts[e.outcome] = counts.get(e.outcome, 0) + 1
        confs = [e.confidence_milli for e in evs]
        digests[ref] = history_digest(evs)
        participants.append({
            "participant_reference": ref,
            "events_accepted": len(evs),
            "missed_intervals": max(evs[-1].seq + 1 - len(evs), 0),
            "min_confidence_milli": min(confs),
            "mean_confidence_milli": sum(confs) // len(confs),
            "final_outcome": evs[-1].outcome,
            "reject_transitions": drops,
            "outcome_counts": counts,
            "history_sha256": digests[ref],
        })

    duration = max(now - session.started_at_ms, 0)
    paused_ms = _uncovered_ms(gaps, session.started_at_ms, now)
    coverage = {
        "session_duration_ms": duration,
        "paused_ms": paused_ms,
        "gap_count": len(gaps),
        "coverage_milli": 1000 if duration == 0 else max(0, (duration - paused_ms) * 1000 // duration),
        "participants_declared": session.participant_count,
        "participants_observed": len(by_ref),
        "gaps": [{"start_ms": g.start_ms, "end_ms": g.end_ms or now, "reason": g.reason}
                 for g in gaps[:MAX_GAPS_LISTED]],
        "gaps_truncated": 1 if len(gaps) > MAX_GAPS_LISTED else 0,
    }
    payload = {
        "v": ATTESTATION_VERSION,
        "type": "certivo_session_attestation",
        "session_id": session.id,
        "partner_id": session.partner_id,
        "use_case": session.use_case,
        "started_at_ms": session.started_at_ms,
        "ended_at_ms": now,
        "issued_at_ms": now,
        "key_id": signer.key_id,
        "policy": {"policy_id": session.policy_id, "version": session.policy_version,
                   "config_sha256": config_sha256(session.policy_config)},
        "participants": participants,
        "coverage": coverage,
        # The whole scored history, as one fingerprint (FR-4.1 extended). See history_digest.
        "history": {"events_total": len(events), "root_sha256": history_root(digests)},
    }
    if session.call_session_reference:
        payload["call_session_reference"] = session.call_session_reference

    rec = SessionAttestation(session_id=session.id, status="pending", payload=payload, issued_at_ms=now,
                             attempts=0, next_attempt_at_ms=now)
    db.add(rec)
    _try_to_sign(rec, signer, now, settings.attestation_retry_max_wait_s)
    db.commit()
    return rec


def session_status(db: Session, session: ContinuousSession) -> dict:
    refs = list(db.scalars(participant_refs_stmt(session)))
    participants = []
    for ref in sorted(refs):
        # Partners poll this endpoint, so read the newest row and a count, not every row.
        latest = db.scalar(recent_events_stmt(session, ref, 1))
        accepted = db.scalar(event_count_stmt(session, ref))
        participants.append({
            "participant_reference": ref,
            "confidence_milli": latest.confidence_milli,
            "effective_confidence_milli": latest.effective_confidence_milli,
            "outcome": latest.outcome,
            "explanation": latest.explanation,
            "last_seq": latest.seq,
            "events_accepted": accepted,
        })
    return {"session_id": session.id, "session_status": session.status,
            "participants": participants}
