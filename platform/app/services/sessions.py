from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.attestation import MAX_GAPS_LISTED, Signer, config_sha256
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
from app.policy import evaluate
from app.schemas import ScoreEventIn, ScoreEventOut, SessionStartIn
from app.security import new_sdk_token, sha256_hex


def _emit(db: Session, partner_id: str, event_type: str, payload: dict, now: int) -> None:
    db.add(WebhookOutbox(partner_id=partner_id, event_type=event_type,
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


def _outcome_out(event: ScoreEvent, duplicate: bool) -> ScoreEventOut:
    return ScoreEventOut(accepted=True, seq=event.seq,
                         current_policy_outcome=event.outcome, duplicate=duplicate)


def _close_open_gap(db: Session, session: ContinuousSession, now: int) -> None:
    gap = db.scalar(select(CoverageGap).where(CoverageGap.session_id == session.id,
                                              CoverageGap.end_ms.is_(None)))
    if gap:
        gap.end_ms = now


def ingest_score_event(db: Session, settings: Settings, session: ContinuousSession,
                       req: ScoreEventIn, now: int) -> ScoreEventOut:
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

    # 2. Sanity-check the (now authenticated) timing fields.
    span = req.interval_end_ms - req.interval_start_ms
    if span <= 0 or span > settings.max_interval_ms:
        raise ApiError(422, "invalid_interval",
                       f"interval must be 1..{settings.max_interval_ms} ms long")
    if req.interval_end_ms > now + settings.max_clock_skew_ms:
        raise ApiError(422, "timestamp_in_future", "interval_end_ms is ahead of server time")

    # 3. Idempotency / ordering per participant.
    ref = req.participant_reference
    existing = db.scalar(select(ScoreEvent).where(
        ScoreEvent.session_id == session.id, ScoreEvent.participant_ref == ref,
        ScoreEvent.seq == req.seq))
    if existing:
        if existing.signature == req.device_signature:
            return _outcome_out(existing, duplicate=True)
        raise ApiError(409, "seq_conflict", "A different packet already used this seq")
    recent = list(db.scalars(select(ScoreEvent).where(
        ScoreEvent.session_id == session.id, ScoreEvent.participant_ref == ref)
        .order_by(ScoreEvent.seq.desc()).limit(max(session.policy_config["drop_consecutive"], 1))))
    last = recent[0] if recent else None
    if last and req.seq < last.seq:
        raise ApiError(409, "seq_out_of_order", "seq must increase per participant")
    if last and req.interval_end_ms < last.interval_end_ms:
        raise ApiError(409, "non_monotonic_interval", "interval_end_ms went backwards")

    # 4. A valid packet while paused implicitly resumes the session.
    if session.status == "paused":
        _close_open_gap(db, session, now)
        session.status = "active"

    prior = [e.confidence_milli for e in reversed(recent)]
    outcome = evaluate(session.policy_config, prior, req.confidence_milli)
    event = ScoreEvent(
        session_id=session.id, participant_ref=ref, seq=req.seq, device_id=device.id,
        interval_start_ms=req.interval_start_ms, interval_end_ms=req.interval_end_ms,
        confidence_milli=req.confidence_milli, model_version=req.model_version,
        explanation=req.explanation.model_dump(), signature=req.device_signature,
        outcome=outcome, received_at_ms=now,
    )
    db.add(event)
    if outcome == "reject" and (last is None or last.outcome != "reject"):
        _emit(db, session.partner_id, "session.confidence_dropped", {
            "session_id": session.id, "participant_reference": ref, "seq": req.seq,
            "confidence_milli": req.confidence_milli, "occurred_at_ms": req.interval_end_ms,
        }, now)
    try:
        db.commit()
    except IntegrityError as exc:  # concurrent duplicate
        db.rollback()
        raise ApiError(409, "seq_conflict", "A packet with this seq was just recorded") from exc
    return _outcome_out(event, duplicate=False)


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


def end_session(db: Session, signer: Signer, session: ContinuousSession, now: int) -> dict:
    stored = db.get(SessionAttestation, session.id)
    if session.status == "ended" and stored:
        return stored.attestation

    _close_open_gap(db, session, now)
    session.status = "ended"
    session.ended_at_ms = now
    events = list(db.scalars(select(ScoreEvent).where(ScoreEvent.session_id == session.id)
                             .order_by(ScoreEvent.participant_ref, ScoreEvent.seq)))
    gaps = list(db.scalars(select(CoverageGap).where(CoverageGap.session_id == session.id)
                           .order_by(CoverageGap.start_ms)))

    by_ref: dict[str, list[ScoreEvent]] = {}
    for e in events:
        by_ref.setdefault(e.participant_ref, []).append(e)
    participants = []
    for ref in sorted(by_ref):
        evs = by_ref[ref]
        drops, prev = 0, None
        for e in evs:
            if e.outcome == "reject" and prev != "reject":
                drops += 1
            prev = e.outcome
        confs = [e.confidence_milli for e in evs]
        participants.append({
            "participant_reference": ref,
            "events_accepted": len(evs),
            "missed_intervals": max(evs[-1].seq + 1 - len(evs), 0),
            "min_confidence_milli": min(confs),
            "mean_confidence_milli": sum(confs) // len(confs),
            "final_outcome": evs[-1].outcome,
            "reject_transitions": drops,
        })

    duration = max(now - session.started_at_ms, 0)
    paused_ms = sum((g.end_ms or now) - g.start_ms for g in gaps)
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
        "v": 1,
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
    }
    if session.call_session_reference:
        payload["call_session_reference"] = session.call_session_reference
    attestation = signer.sign_attestation(payload)
    db.add(SessionAttestation(session_id=session.id, attestation=attestation, issued_at_ms=now))
    db.commit()
    return attestation


def session_status(db: Session, session: ContinuousSession) -> dict:
    refs = list(db.scalars(select(ScoreEvent.participant_ref)
                           .where(ScoreEvent.session_id == session.id).distinct()))
    participants = []
    for ref in sorted(refs):
        evs = list(db.scalars(select(ScoreEvent).where(
            ScoreEvent.session_id == session.id, ScoreEvent.participant_ref == ref)
            .order_by(ScoreEvent.seq.desc())))
        latest = evs[0]
        participants.append({
            "participant_reference": ref,
            "confidence_milli": latest.confidence_milli,
            "outcome": latest.outcome,
            "explanation": latest.explanation,
            "last_seq": latest.seq,
            "events_accepted": len(evs),
        })
    return {"session_id": session.id, "session_status": session.status,
            "participants": participants}
