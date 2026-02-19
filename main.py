from fastapi import FastAPI, Query, Request, UploadFile, File, Form, Depends
from fastapi.middleware.cors import CORSMiddleware
import uuid
from challenge_engine import generate_adaptive_challenges
from typing import List
from fastapi.responses import FileResponse
import os
from human_verification import run_human_verification
import tempfile
from logger import log_event
from datetime import datetime, timedelta
import cv2
from typing import Dict, Any
import json

# Database imports
from sqlalchemy.orm import Session
from database import (
    get_db, store_challenge, get_challenge, delete_challenge,
    store_challenge_result, get_session_results, store_session,
    is_device_trusted, update_device_trust, cleanup_expired_challenges,
    get_device_stats, get_bot_statistics, get_bot_reports
)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"]
)


# ============================================================================
# BOT DETECTION HELPERS
# ============================================================================

def analyze_backend_bot_signals(request: Request) -> Dict[str, Any]:
    signals = {}
    suspicion_score = 0
    headers = dict(request.headers)
    user_agent = headers.get("user-agent", "").lower()

    bot_keywords = [
        'headless', 'selenium', 'puppeteer', 'phantomjs',
        'bot', 'crawler', 'spider', 'scraper', 'python-requests',
        'curl', 'wget', 'automation'
    ]
    if any(k in user_agent for k in bot_keywords):
        signals['suspicious_user_agent'] = True
        suspicion_score += 5

    for h in ['accept-language', 'accept-encoding']:
        if h not in headers:
            signals[f'missing_{h}'] = True
            suspicion_score += 2

    if not headers.get('accept-language'):
        signals['no_language'] = True
        suspicion_score += 2

    return {
        'suspicion_score': suspicion_score,
        'is_likely_bot': suspicion_score >= 5,
        'signals': signals
    }


# ============================================================================
# ADMIN
# ============================================================================

@app.get("/v1/admin/bot-stats")
async def get_bot_statistics_endpoint(db: Session = Depends(get_db)):
    stats = get_bot_statistics(db)
    recent_reports = get_bot_reports(db, limit=10)
    return {
        "statistics": stats,
        "recent_reports": [
            {
                "device_id": r.device_id,
                "bot_detected": r.bot_detected,
                "suspicion_score": r.suspicion_score,
                "timestamp": r.timestamp_utc.isoformat()
            }
            for r in recent_reports
        ]
    }


@app.post("/v1/bot-report")
async def report_bot_detection(request: Request, db: Session = Depends(get_db)):
    try:
        data = await request.json()
        device_id = data.get("device_id", "unknown")
        log_event(
            event="bot_detection_report",
            session_id=device_id,
            challenge_id=None,
            details=data
        )
        return {"status": "received"}
    except Exception as e:
        return {"status": "error"}


# ============================================================================
# GET CHALLENGES
# ============================================================================

@app.get("/v1/challenge")
async def get_challenge_endpoint(
    request: Request,
    device_id: str = Query(...),
    db: Session = Depends(get_db)
):
    """
    Returns adaptive challenges for a device.
    - Trusted devices  → 1 easy fast-track challenge
    - Untrusted devices → 2 challenges with adaptive difficulty
    """

    # Bot check
    bot_analysis = analyze_backend_bot_signals(request)
    if bot_analysis['is_likely_bot']:
        log_event(
            event="bot_detected_backend",
            session_id=device_id,
            challenge_id=None,
            details=bot_analysis
        )
        return {
            "error": "Automated access detected",
            "code": "BOT_DETECTED",
            "message": "Please use a standard web browser for verification"
        }

    is_trusted = is_device_trusted(db, device_id)
    cleanup_expired_challenges(db)

    num_challenges = 1 if is_trusted else 2

    # ------------------------------------------------------------------ #
    # Fetch recent results so adaptive difficulty can use them            #
    # ------------------------------------------------------------------ #
    recent_db_results = get_session_results(db, device_id)
    prev_results = []
    if recent_db_results:
        prev_results = [
            {
                "challenge_passed":  r.challenge_passed,
                "expected_movement": r.expected_direction,   # stored in DB as expected_direction
                "action_detected":   r.direction_detected,
            }
            for r in recent_db_results
        ]

    # ------------------------------------------------------------------ #
    # Generate challenges                                                 #
    # ------------------------------------------------------------------ #
    challenges = generate_adaptive_challenges(
        prev_results=prev_results,
        num=num_challenges,
        trusted=is_trusted,
        device_id=device_id,
    )

    # ------------------------------------------------------------------ #
    # Store each challenge in DB and build response                       #
    # ------------------------------------------------------------------ #
    normalized = []
    for ch in challenges:
        challenge_id     = ch["challenge_id"]
        instruction      = ch["challenge_value"]
        expected_movement = ch["expected_movement"]         # ← NEW: full movement type
        token_id         = str(uuid.uuid4())
        expires_at       = datetime.utcnow() + timedelta(minutes=5)

        # For backwards-compatibility, also derive expected_direction for
        # left/right challenges
        expected_direction = expected_movement if expected_movement in ("left", "right") else None

        store_challenge(
            db=db,
            challenge_id=challenge_id,
            device_id=device_id,
            instruction=instruction,
            expected_direction=expected_movement,   # reuse column to store full movement type
            token_id=token_id,
            expires_at=expires_at,
            difficulty=ch["difficulty"],
            expected_movement=expected_movement,
        )

        log_event(
            event="challenge_generated",
            session_id=device_id,
            challenge_id=challenge_id,
            details={
                "instruction": instruction,
                "expected_movement": expected_movement,
                "difficulty": ch["difficulty"],
                "fast_track": is_trusted,
            }
        )

        normalized.append({
            "challenge_id":      challenge_id,
            "token_id":          token_id,
            "instruction":       instruction,
            "difficulty":        ch["difficulty"],
            "expected_movement": expected_movement,
            "fast_track":        ch["fast_track"],
        })

    return {
        "trusted_device":     is_trusted,
        "fast_track_enabled": is_trusted,
        "challenges":         normalized,
        "message":            "🚀 Fast-Track Mode Active" if is_trusted else "Standard Verification"
    }


# ============================================================================
# VERIFY CHALLENGE
# ============================================================================

@app.post("/v1/verify")
async def verify_challenge(
    device_id:    str        = Form(...),
    challenge_id: str        = Form(...),
    token_id:     str        = Form(...),
    video:        UploadFile = File(...),
    db:           Session    = Depends(get_db)
):
    """
    Receive video submission, run the correct detector for the challenge type,
    store the result and return pass/fail.
    """
    video_path       = None
    video_size_bytes = 0

    try:
        # ----------------------------------------------------------------#
        # 1. Validate video                                               #
        # ----------------------------------------------------------------#
        if not video.content_type or not video.content_type.startswith("video/"):
            return _reject("Invalid video format")

        MAX_VIDEO_SIZE = 10 * 1024 * 1024   # 10 MB
        video_bytes      = await video.read()
        video_size_bytes = len(video_bytes)

        if video_size_bytes > MAX_VIDEO_SIZE:
            return _reject("Video file too large")

        if video_size_bytes < 1000:
            return _reject("Video file too small or corrupted")

        # ----------------------------------------------------------------#
        # 2. Save to temp file                                            #
        # ----------------------------------------------------------------#
        with tempfile.NamedTemporaryFile(delete=False, suffix=".webm") as tmp:
            tmp.write(video_bytes)
            video_path = tmp.name

        log_event(
            event="video_received",
            session_id=device_id,
            challenge_id=challenge_id,
            details={"video_size_bytes": video_size_bytes}
        )

        # ----------------------------------------------------------------#
        # 3. Load and validate challenge from DB                          #
        # ----------------------------------------------------------------#
        challenge_record = get_challenge(db, challenge_id)

        if not challenge_record:
            return _reject("Challenge not found")

        if challenge_record.token_id != token_id:
            return _reject("Invalid verification token")

        if challenge_record.device_id != device_id:
            return _reject("Challenge does not belong to this device")

        if datetime.utcnow() > challenge_record.expires_at:
            return _reject("Challenge has expired")

        if challenge_record.used:
            return _reject("Challenge already used")

        # ----------------------------------------------------------------#
        # 4. Determine what the challenge expects                         #
        # ----------------------------------------------------------------#
        # expected_direction column stores the full movement type now
        expected_movement = (
            challenge_record.expected_movement
            or challenge_record.expected_direction
            or ""
        )
        instruction = challenge_record.instruction
        difficulty  = challenge_record.difficulty
        is_trusted  = is_device_trusted(db, device_id)

        # ----------------------------------------------------------------#
        # 5. Run human verification                                       #
        # ----------------------------------------------------------------#
        try:
            result = run_human_verification(
                session_id=device_id,
                challenge_id=challenge_id,
                video_path=video_path,
                fast_track=is_trusted,
                expected_movement=expected_movement,
            )

            # Ensure types are correct
            result["challenge_passed"] = bool(result["challenge_passed"])
            result["liveness_score"]   = float(result["liveness_score"])

            log_event(
                event="verification_completed",
                session_id=device_id,
                challenge_id=challenge_id,
                details={
                    "passed":           result["challenge_passed"],
                    "liveness_score":   result["liveness_score"],
                    "expected_movement": expected_movement,
                    "action_detected":  result.get("action_detected", "none"),
                    "fast_track":       is_trusted,
                }
            )

        except Exception as e:
            log_event(
                event="verification_error",
                session_id=device_id,
                challenge_id=challenge_id,
                details={"error": str(e)}
            )
            return _reject("Verification processing failed")

        # ----------------------------------------------------------------#
        # 6. Mark challenge used & store result                           #
        # ----------------------------------------------------------------#
        delete_challenge(db, challenge_id)

        store_challenge_result(
            db=db,
            session_id=device_id,
            device_id=device_id,
            challenge_id=challenge_id,
            instruction=instruction,
            expected_direction=expected_movement,   # stores full movement type
            challenge_passed=result["challenge_passed"],
            liveness_score=result["liveness_score"],
            direction_detected=result.get("action_detected", "none"),
            direction_matched=result.get("action_matched", False),
            fast_track=is_trusted,
            video_size_bytes=video_size_bytes,
            difficulty=difficulty,
        )

        return result

    except Exception as e:
        log_event(
            event="endpoint_error",
            session_id=device_id,
            challenge_id=challenge_id,
            details={"error": str(e)}
        )
        return _reject("Server error during verification")

    finally:
        if video_path and os.path.exists(video_path):
            try:
                os.remove(video_path)
            except Exception:
                pass


# ============================================================================
# FINALIZE SESSION
# ============================================================================

@app.post("/v1/finalize")
async def finalize_verification(request: Request, db: Session = Depends(get_db)):
    data      = await request.json()
    results   = data.get("results", [])
    device_id = data.get("device_id", "unknown")

    if not results:
        return {"trust_score": 0, "trust_level": "low"}

    db_results = get_session_results(db, device_id)

    if db_results and len(db_results) > 0:
        total_challenges = len(db_results)
        failed_challenges = sum(1 for r in db_results if not r.challenge_passed)
        total_liveness = sum(
            r.liveness_score * 100 if r.challenge_passed else 0
            for r in db_results
        )
    else:
        total_challenges  = len(results)
        failed_challenges = sum(1 for r in results if not r.get("challenge_passed"))
        total_liveness    = sum(
            r.get("liveness_score", 0) * 100 if r.get("challenge_passed") else 0
            for r in results
        )

    score = int(total_liveness / total_challenges) if total_challenges > 0 else 0

    if score >= 80:
        level = "high"
    elif score >= 50:
        level = "medium"
    else:
        level = "low"

    session_id   = f"session_{device_id}_{int(datetime.utcnow().timestamp())}"
    is_fast_track = is_device_trusted(db, device_id)

    store_session(
        db=db,
        session_id=session_id,
        device_id=device_id,
        trust_score=float(score),
        trust_level=level,
        failed_challenges=failed_challenges,
        total_challenges=total_challenges,
        fast_track=is_fast_track,
    )

    update_device_trust(
        db=db,
        device_id=device_id,
        trust_level=level,
        verification_passed=(level in ["high", "medium"]),
    )

    log_event(
        event="session_finalized",
        session_id=session_id,
        challenge_id=None,
        details={
            "device_id":        device_id,
            "trust_score":      score,
            "trust_level":      level,
            "total_challenges": total_challenges,
            "failed_challenges": failed_challenges,
        }
    )

    return {"trust_score": score, "trust_level": level, "session_id": session_id}


# ============================================================================
# DEVICE STATS
# ============================================================================

@app.get("/v1/device/{device_id}/stats")
async def get_device_statistics(device_id: str, db: Session = Depends(get_db)):
    stats = get_device_stats(db, device_id)
    if not stats:
        return {"error": "Device not found", "device_id": device_id}
    return stats


# ============================================================================
# SERVE FRONTEND
# ============================================================================

@app.get("/")
def read_index():
    if os.path.exists("index.html"):
        return FileResponse("index.html")
    return {"detail": "index.html not found"}


# ============================================================================
# HELPER
# ============================================================================

def _reject(reason: str) -> dict:
    """Return a standardised failure response."""
    return {
        "challenge_passed":  False,
        "liveness_score":    0.0,
        "direction_detected": "none",
        "direction_matched":  False,
        "action_detected":   "none",
        "action_matched":    False,
        "error":             reason,
    }
