from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import ApiError
from app.models import ContinuousSession, Partner
from app.schemas import PauseIn, ScoreEventIn, ScoreEventOut, SessionStartIn, SessionStartOut
from app.security import require_partner, require_sdk_session
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
def start(body: SessionStartIn, request: Request, partner: Partner = Depends(require_partner),
          db: Session = Depends(get_db)):
    session, token = svc.start_session(db, partner, body, _now(request))
    return SessionStartOut(
        id=session.id, status=session.status, sdk_token=token,
        re_evaluation_interval_ms=session.policy_config["re_evaluation_interval_ms"])


@router.post("/internal/v1/sessions/continuous/{session_id}/score-events",
             response_model=ScoreEventOut)
def score_event(body: ScoreEventIn, request: Request,
                session: ContinuousSession = Depends(require_sdk_session),
                db: Session = Depends(get_db)):
    return svc.ingest_score_event(db, request.app.state.settings, session, body, _now(request))


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
def end(session_id: str, request: Request, partner: Partner = Depends(require_partner),
        db: Session = Depends(get_db)):
    session = _partner_session(db, partner, session_id)
    attestation = svc.end_session(db, request.app.state.signer, session, _now(request))
    return {"id": session.id, "status": "ended", "attestation": attestation,
            "coverage_summary": attestation["payload"]["coverage"]}


@router.get("/v1/sessions/continuous/{session_id}/status")
def status(session_id: str, partner: Partner = Depends(require_partner),
           db: Session = Depends(get_db)):
    return svc.session_status(db, _partner_session(db, partner, session_id))
