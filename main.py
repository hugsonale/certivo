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

# Database imports
from sqlalchemy.orm import Session
from database import (
    get_db, store_challenge, get_challenge, delete_challenge,
    store_challenge_result, get_session_results, store_session,
    is_device_trusted, update_device_trust, cleanup_expired_challenges,
    get_device_stats
)

app = FastAPI()


# Allow frontend to call API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"]
)


@app.get("/v1/challenge")
async def get_challenge_endpoint(request: Request, device_id: str = Query(...), db: Session = Depends(get_db)):
    """
    Returns adaptive challenges with unique token_id for verification.
    Trusted devices get Fast-Track mode (fewer challenges).
    ALL DATA STORED IN DATABASE.
    """
    user_agent = request.headers.get("user-agent", "unknown")
    
    # Check if device is trusted (from DATABASE)
    is_trusted = is_device_trusted(db, device_id)
    
    # Cleanup expired challenges periodically
    cleanup_expired_challenges(db)

    # Adjust challenge count based on trust
    num_challenges = 1 if is_trusted else 3
    
    # Generate challenges
    challenges = generate_adaptive_challenges(
        prev_results=[], 
        num=num_challenges, 
        trusted=is_trusted
    )

    # Normalize challenges and STORE IN DATABASE
    normalized = []
    for ch in challenges:
        challenge_id = ch.get("challenge_id")
        instruction = ch.get("challenge_value", "")
        
        # Extract expected direction from instruction
        expected_direction = None
        instruction_lower = instruction.lower()
        
        if "left" in instruction_lower:
            expected_direction = "left"
        elif "right" in instruction_lower:
            expected_direction = "right"
        
        # Generate token
        token_id = str(uuid.uuid4())
        expires_at = datetime.utcnow() + timedelta(minutes=5)
        
        # STORE CHALLENGE IN DATABASE (replaces in-memory storage)
        store_challenge(
            db=db,
            challenge_id=challenge_id,
            device_id=device_id,
            instruction=instruction,
            expected_direction=expected_direction,
            token_id=token_id,
            expires_at=expires_at,
            difficulty=ch.get("difficulty", "medium"),
            expected_movement=ch.get("expected_movement")
        )
        
        log_event(
            event="challenge_generated",
            session_id=device_id,
            challenge_id=challenge_id,
            details={
                "instruction": instruction,
                "expected_direction": expected_direction,
                "fast_track": is_trusted
            }
        )
        
        normalized.append({
            "challenge_id": challenge_id,
            "token_id": token_id,
            "instruction": instruction,
            "difficulty": ch.get("difficulty", "medium"),
            "fast_track": ch.get("fast_track", False)
        })

    return {
        "trusted_device": is_trusted,
        "fast_track_enabled": is_trusted,
        "challenges": normalized,
        "message": "🚀 Fast-Track Mode Active" if is_trusted else "Standard Verification"
    }


@app.post("/v1/verify")
async def verify_challenge(
    device_id: str = Form(...),
    challenge_id: str = Form(...),
    token_id: str = Form(...),
    video: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    """
    Receives video submission and runs real human verification with direction validation.
    ALL RESULTS STORED IN DATABASE.
    """
    video_path = None
    video_size_bytes = 0
    
    try:
        # 1. Validate video file
        if not video.content_type or not video.content_type.startswith('video/'):
            log_event(
                event="verification_rejected",
                session_id=device_id,
                challenge_id=challenge_id,
                details={"reason": "invalid_content_type", "content_type": video.content_type}
            )
            return {
                "challenge_passed": False,
                "liveness_score": 0.0,
                "direction_detected": "none",
                "direction_matched": False,
                "error": "Invalid video format"
            }
        
        # 2. Check video size (prevent DoS attacks)
        MAX_VIDEO_SIZE = 10 * 1024 * 1024  # 10MB
        video_bytes = await video.read()
        video_size_bytes = len(video_bytes)
        
        if video_size_bytes > MAX_VIDEO_SIZE:
            log_event(
                event="verification_rejected",
                session_id=device_id,
                challenge_id=challenge_id,
                details={"reason": "file_too_large", "size_bytes": video_size_bytes}
            )
            return {
                "challenge_passed": False,
                "liveness_score": 0.0,
                "direction_detected": "none",
                "direction_matched": False,
                "error": "Video file too large"
            }
        
        if video_size_bytes < 1000:
            log_event(
                event="verification_rejected",
                session_id=device_id,
                challenge_id=challenge_id,
                details={"reason": "file_too_small", "size_bytes": video_size_bytes}
            )
            return {
                "challenge_passed": False,
                "liveness_score": 0.0,
                "direction_detected": "none",
                "direction_matched": False,
                "error": "Video file too small or corrupted"
            }

        # 3. Save uploaded video to temp file
        with tempfile.NamedTemporaryFile(delete=False, suffix=".webm") as tmp:
            tmp.write(video_bytes)
            video_path = tmp.name
        
        log_event(
            event="video_received",
            session_id=device_id,
            challenge_id=challenge_id,
            details={"video_size_bytes": video_size_bytes, "temp_path": video_path}
        )

        # GET CHALLENGE FROM DATABASE
        challenge_record = get_challenge(db, challenge_id)
        
        if not challenge_record:
            log_event(
                event="verification_rejected",
                session_id=device_id,
                challenge_id=challenge_id,
                details={"reason": "challenge_not_found"}
            )
            return {
                "challenge_passed": False,
                "liveness_score": 0.0,
                "direction_detected": "none",
                "direction_matched": False,
                "error": "Challenge not found"
            }
        
        # VALIDATE TOKEN_ID
        if challenge_record.token_id != token_id:
            log_event(
                event="verification_rejected",
                session_id=device_id,
                challenge_id=challenge_id,
                details={
                    "reason": "invalid_token",
                    "expected_token": challenge_record.token_id[:8] + "...",
                    "received_token": token_id[:8] + "..."
                }
            )
            return {
                "challenge_passed": False,
                "liveness_score": 0.0,
                "direction_detected": "none",
                "direction_matched": False,
                "error": "Invalid verification token"
            }
        
        # Validate challenge belongs to this device

        # Validate challenge belongs to this device
        if challenge_record.device_id != device_id:
            log_event(
                event="verification_rejected",
                session_id=device_id,
                challenge_id=challenge_id,
                details={"reason": "device_mismatch"}
            )
            return {
                "challenge_passed": False,
                "liveness_score": 0.0,
                "direction_detected": "none",
                "direction_matched": False,
                "error": "Challenge does not belong to this device"
            }
        
        # Check if challenge expired
        if datetime.utcnow() > challenge_record.expires_at:
            log_event(
                event="verification_rejected",
                session_id=device_id,
                challenge_id=challenge_id,
                details={"reason": "challenge_expired"}
            )
            return {
                "challenge_passed": False,
                "liveness_score": 0.0,
                "direction_detected": "none",
                "direction_matched": False,
                "error": "Challenge has expired"
            }
        
        # Check if challenge already used
        if challenge_record.used:
            log_event(
                event="verification_rejected",
                session_id=device_id,
                challenge_id=challenge_id,
                details={"reason": "challenge_already_used"}
            )
            return {
                "challenge_passed": False,
                "liveness_score": 0.0,
                "direction_detected": "none",
                "direction_matched": False,
                "error": "Challenge already used"
            }
        
        expected_direction = challenge_record.expected_direction
        instruction = challenge_record.instruction
        difficulty = challenge_record.difficulty

        # Check if device is trusted (from DATABASE)
        is_trusted = is_device_trusted(db, device_id)

        # 5. Run human verification logic with error handling and direction validation
        try:
            result = run_human_verification(
                session_id=device_id,
                challenge_id=challenge_id,
                video_path=video_path,
                fast_track=is_trusted,
                expected_direction=expected_direction
            )
            
            # Validate result structure
            if not isinstance(result, dict):
                raise ValueError("Verification returned invalid result type")
            
            required_fields = ["challenge_passed", "liveness_score", "direction_detected", "direction_matched"]
            for field in required_fields:
                if field not in result:
                    raise ValueError(f"Verification result missing required field: {field}")
            
            # Ensure proper types
            result["challenge_passed"] = bool(result["challenge_passed"])
            result["liveness_score"] = float(result["liveness_score"])
            result["direction_detected"] = str(result["direction_detected"])
            result["direction_matched"] = bool(result["direction_matched"])
            
            # Log successful verification
            log_event(
                event="verification_completed",
                session_id=device_id,
                challenge_id=challenge_id,
                details={
                    "passed": result["challenge_passed"],
                    "liveness_score": result["liveness_score"],
                    "direction_detected": result["direction_detected"],
                    "direction_matched": result["direction_matched"],
                    "expected_direction": expected_direction,
                    "fast_track": is_trusted
                }
            )
            
        except FileNotFoundError as e:
            log_event(
                event="verification_error",
                session_id=device_id,
                challenge_id=challenge_id,
                details={"error": "video_file_not_found", "message": str(e)}
            )
            return {
                "challenge_passed": False,
                "liveness_score": 0.0,
                "direction_detected": "none",
                "direction_matched": False,
                "error": "Video file not accessible"
            }
            
        except cv2.error as e:
            log_event(
                event="verification_error",
                session_id=device_id,
                challenge_id=challenge_id,
                details={"error": "opencv_error", "message": str(e)}
            )
            return {
                "challenge_passed": False,
                "liveness_score": 0.0,
                "direction_detected": "none",
                "direction_matched": False,
                "error": "Video processing failed"
            }
            
        except ValueError as e:
            log_event(
                event="verification_error",
                session_id=device_id,
                challenge_id=challenge_id,
                details={"error": "validation_error", "message": str(e)}
            )
            return {
                "challenge_passed": False,
                "liveness_score": 0.0,
                "direction_detected": "none",
                "direction_matched": False,
                "error": "Verification result validation failed"
            }
            
        except Exception as e:
            log_event(
                event="verification_error",
                session_id=device_id,
                challenge_id=challenge_id,
                details={"error": "unexpected_error", "message": str(e), "type": type(e).__name__}
            )
            return {
                "challenge_passed": False,
                "liveness_score": 0.0,
                "direction_detected": "none",
                "direction_matched": False,
                "error": "Verification failed due to unexpected error"
            }

        # DELETE USED CHALLENGE FROM DATABASE (prevents replay attacks)
        delete_challenge(db, challenge_id)

        # STORE CHALLENGE RESULT IN DATABASE
        store_challenge_result(
            db=db,
            session_id=device_id,  # Using device_id as session_id for now
            device_id=device_id,
            challenge_id=challenge_id,
            instruction=instruction,
            expected_direction=expected_direction,
            challenge_passed=result["challenge_passed"],
            liveness_score=result["liveness_score"],
            direction_detected=result["direction_detected"],
            direction_matched=result["direction_matched"],
            fast_track=is_trusted,
            video_size_bytes=video_size_bytes,
            difficulty=difficulty
        )

        return result

    except Exception as e:
        # Catch-all for any unexpected errors in the endpoint itself
        log_event(
            event="endpoint_error",
            session_id=device_id,
            challenge_id=challenge_id,
            details={"error": str(e), "type": type(e).__name__}
        )
        return {
            "challenge_passed": False,
            "liveness_score": 0.0,
            "direction_detected": "none",
            "direction_matched": False,
            "error": "Server error during verification"
        }
    
    finally:
        # Always cleanup temp file, even if errors occurred
        if video_path and os.path.exists(video_path):
            try:
                os.remove(video_path)
                log_event(
                    event="temp_file_cleanup",
                    session_id=device_id,
                    challenge_id=challenge_id,
                    details={"temp_path": video_path, "status": "success"}
                )
            except Exception as cleanup_error:
                log_event(
                    event="temp_file_cleanup",
                    session_id=device_id,
                    challenge_id=challenge_id,
                    details={"temp_path": video_path, "status": "failed", "error": str(cleanup_error)}
                )


@app.post("/v1/finalize")
async def finalize_verification(request: Request, db: Session = Depends(get_db)):
    """
    Calculates final trust score based on all challenges for the device.
    STORES SESSION IN DATABASE.
    """
    data = await request.json()
    results = data.get("results", [])
    device_id = data.get("device_id", "unknown")

    if not results:
        return {"trust_score": 0, "trust_level": "low"}

    # GET RESULTS FROM DATABASE instead of relying on frontend
    db_results = get_session_results(db, device_id)
    
    if not db_results:
        # Fallback to frontend results if database query returns nothing
        total_challenges = len(results)
        failed_challenges = sum(1 for r in results if not r.get("challenge_passed"))
        score = int(sum(100 if r.get("challenge_passed") else 0 for r in results) / total_challenges)
    else:
        # Use database results (more reliable)
        total_challenges = len(db_results)
        failed_challenges = sum(1 for r in db_results if not r.challenge_passed)
        passed_challenges = total_challenges - failed_challenges
        score = int((passed_challenges / total_challenges) * 100) if total_challenges > 0 else 0

    if score >= 80:
        level = "high"
    elif score >= 50:
        level = "medium"
    else:
        level = "low"

    # STORE SESSION IN DATABASE
    session_id = f"session_{device_id}_{int(datetime.utcnow().timestamp())}"
    is_fast_track = is_device_trusted(db, device_id)
    
    store_session(
        db=db,
        session_id=session_id,
        device_id=device_id,
        trust_score=float(score),
        trust_level=level,
        failed_challenges=failed_challenges,
        total_challenges=total_challenges,
        fast_track=is_fast_track
    )

    # UPDATE DEVICE TRUST IN DATABASE
    verification_passed = (level in ["high", "medium"])
    update_device_trust(
        db=db,
        device_id=device_id,
        trust_level=level,
        verification_passed=verification_passed
    )

    log_event(
        event="session_finalized",
        session_id=session_id,
        challenge_id=None,
        details={
            "device_id": device_id,
            "trust_score": score,
            "trust_level": level,
            "total_challenges": total_challenges,
            "failed_challenges": failed_challenges
        }
    )

    return {"trust_score": score, "trust_level": level, "session_id": session_id}


@app.get("/v1/device/{device_id}/stats")
async def get_device_statistics(device_id: str, db: Session = Depends(get_db)):
    """
    Get statistics for a specific device.
    Returns verification history, success rates, and trust metrics.
    """
    stats = get_device_stats(db, device_id)
    if not stats:
        return {"error": "Device not found", "device_id": device_id}
    return stats


@app.get("/")
def read_index():
    """Serve index.html at root"""
    html_path = "index.html"
    if os.path.exists(html_path):
        return FileResponse(html_path)
    return {"detail": "index.html not found"}