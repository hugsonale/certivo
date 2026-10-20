from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import ApiError
from app.models import ContinuousSession, Partner, SessionAttestation
from app.schemas import (
    PauseIn,
    ScoreBatchIn,
    ScoreBatchOut,
    ScoreEventIn,
    ScoreEventOut,
    SessionStartIn,
    SessionStartOut,
)
from app.security import AuthContext, require_scope, require_sdk_session
from app.services import sessions as svc

router = APIRouter()


def _now(request: Request) -> int:
    return request.app.state.clock()


def _partner_session(db: Session, partner: Partner, session_id: str) -> ContinuousSession:
    session = db.get(ContinuousSession, session_id)
    if session is None or session.partner_id != partner.id:
        raise ApiError(404, "session_not_found", "Session not found")
    return session


@router.post("/v1/sessions/continuous", status_code=201, response_model=SessionStartOut)
def start(body: SessionStartIn, request: Request,
          ctx: AuthContext = Depends(require_scope("sessions:write")),
          db: Session = Depends(get_db)):
    ttl_ms = request.app.state.settings.sdk_token_ttl_seconds * 1000
    session, token = svc.start_session(db, ctx.partner, body, _now(request), ttl_ms)
    return SessionStartOut(
        id=session.id, status=session.status, sdk_token=token,
        sdk_token_expires_at_ms=session.sdk_token_expires_at_ms,
        re_evaluation_interval_ms=session.policy_config["re_evaluation_interval_ms"])


@router.post("/internal/v1/sessions/continuous/{session_id}/score-events",
             response_model=ScoreEventOut)
def score_event(body: ScoreEventIn, request: Request,
                session: ContinuousSession = Depends(require_sdk_session),
                db: Session = Depends(get_db)):
    return svc.ingest_score_event(db, request.app.state.settings, session, body, _now(request))


@router.post("/internal/v1/sessions/continuous/{session_id}/score-events/batch",
             response_model=ScoreBatchOut)
def score_event_batch(body: ScoreBatchIn, request: Request,
                      session: ContinuousSession = Depends(require_sdk_session),
                      db: Session = Depends(get_db)):
    return svc.ingest_score_batch(db, request.app.state.settings, session, body.packets,
                                  _now(request))


@router.post("/internal/v1/sessions/continuous/{session_id}/pause", status_code=204)
def pause(request: Request, body: PauseIn | None = None,
          session: ContinuousSession = Depends(require_sdk_session),
          db: Session = Depends(get_db)):
    svc.pause_session(db, session, (body or PauseIn()).reason, _now(request))


@router.post("/internal/v1/sessions/continuous/{session_id}/resume", status_code=204)
def resume(request: Request, session: ContinuousSession = Depends(require_sdk_session),
           db: Session = Depends(get_db)):
    svc.resume_session(db, session, _now(request))


@router.post("/v1/sessions/continuous/{session_id}/end")
def end(session_id: str, request: Request,
        ctx: AuthContext = Depends(require_scope("sessions:write")),
        db: Session = Depends(get_db)):
    session = _partner_session(db, ctx.partner, session_id)
    rec = svc.end_session(db, request.app.state.signer, request.app.state.settings, session,
                          _now(request))
    return _attestation_response(session, rec, request.app.state.settings)


def _attestation_response(session: ContinuousSession, rec, settings):
    """200 with the signed attestation, or 202 if the signer is unreachable and it is queued. In both
    cases the call has ended and its record exists; the coverage summary is always included."""
    if rec.status == "signed":
        return {"id": session.id, "status": "ended", "attestation_status": "signed",
                "attestation": rec.attestation, "coverage_summary": rec.attestation["payload"]["coverage"]}
    return JSONResponse(status_code=202, content={
        "id": session.id, "status": "ended", "attestation_status": "pending", "attestation": None,
        "coverage_summary": rec.payload["coverage"],
        "retry_after_s": settings.attestation_retry_max_wait_s})


@router.get("/v1/sessions/continuous/{session_id}/attestation")
def get_attestation(session_id: str, request: Request,
                    ctx: AuthContext = Depends(require_scope("sessions:read")),
                    db: Session = Depends(get_db)):
    """The signed attestation for a finished call. 202 while it is still waiting to be signed."""
    session = _partner_session(db, ctx.partner, session_id)
    rec = db.get(SessionAttestation, session.id)
    if rec is None:
        raise ApiError(409, "attestation_not_ready", "The session has not ended, so it has no attestation yet")
    return _attestation_response(session, rec, request.app.state.settings)


@router.get("/v1/sessions/continuous/{session_id}/status")
def status(session_id: str, ctx: AuthContext = Depends(require_scope("sessions:read")),
           db: Session = Depends(get_db)):
    return svc.session_status(db, _partner_session(db, ctx.partner, session_id))
