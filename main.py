from fastapi import FastAPI, UploadFile, File, Form, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from pydantic import BaseModel
from typing import List, Optional
import time, uuid, hashlib, os

from challenge_engine import generate_challenges
from human_verification import run_human_verification

app = FastAPI()

# -------------------- CORS --------------------
origins = [
    "http://127.0.0.1:5500",
    "http://localhost:5500",
    "http://127.0.0.1:8000"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------- UPLOADS --------------------
os.makedirs("uploads", exist_ok=True)

# -------------------- IN-MEMORY SESSION LOG --------------------
# Stores all sessions with full per-challenge metrics
session_log = []

# -------------------- GET CHALLENGES --------------------
@app.get("/v1/challenge")
def get_challenge():
    challenges = generate_challenges(num=3)

    # Add creation timestamp
    for ch in challenges:
        ch["created_at"] = time.time()

    return {
        "challenges": [
            {
                "challenge_id": ch["challenge_id"],
                "challenge_type": ch["challenge_type"],
                "instruction": ch["challenge_value"],
                "expires_in": 60
            } for ch in challenges
        ]
    }

# -------------------- VERIFY --------------------
@app.post("/v1/verify")
def verify(
    challenge_id: str = Form(...),
    device_id: str = Form(...),
    video: UploadFile = File(...),
    audio: UploadFile = File(None)
):
    # Save video/audio
    video_path = f"uploads/{uuid.uuid4()}_{video.filename}"
    with open(video_path, "wb") as f:
        f.write(video.file.read())

    audio_path = None
    if audio:
        audio_path = f"uploads/{uuid.uuid4()}_{audio.filename}"
        with open(audio_path, "wb") as f:
            f.write(audio.file.read())

    result = run_human_verification(video_path, audio_path, "generic")

    raw_token = f"{device_id}{time.time()}".encode()
    trusted_device_token = hashlib.sha256(raw_token).hexdigest()

    return {
        "challenge_passed": result["challenge_passed"],
        "liveness_score": result.get("liveness_score", 0),
        "lip_sync_score": result.get("lip_sync_score", 0),
        "reaction_time": result.get("reaction_time", 1.0),
        "facial_stability": result.get("facial_stability", 1.0),
        "blink_count": result.get("blink_count", 0),
        "replay_flag": result.get("replay_flag", False),
        "trusted_device_token": trusted_device_token,
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
    }

# -------------------- FINALIZE SESSION --------------------
class ChallengeResultV2(BaseModel):
    liveness_score: float
    lip_sync_score: float
    challenge_passed: bool
    reaction_time: float          # normalized 0-1
    facial_stability: float       # normalized 0-1
    blink_count: int

class FinalizeRequestV2(BaseModel):
    results: List[ChallengeResultV2]
    device_id: str

@app.post("/v1/finalize")
def finalize_session_v2(payload: FinalizeRequestV2):
    results = payload.results
    device_id = payload.device_id

    if not results:
        return {
            "trust_score": 0,
            "trust_level": "low",
            "reason": "no_results"
        }

    session_id = str(uuid.uuid4())  # unique session ID

    # -------------------- NORMALIZE METRICS & CALCULATE TRUST --------------------
    trust_scores = []
    failed_challenges = 0

    for r in results:
        liveness = max(0, min(1, r.liveness_score))
        lip_sync = max(0, min(1, r.lip_sync_score))
        reaction_time = max(0, min(1, r.reaction_time))
        stability = max(0, min(1, r.facial_stability))

        blink_penalty = 0
        if r.blink_count > 5:
            blink_penalty = min((r.blink_count - 5) * 0.02, 0.2)

        challenge_trust = (
            liveness * 0.35 +
            lip_sync * 0.25 +
            reaction_time * 0.15 +
            stability * 0.15 -
            blink_penalty
        )

        trust_scores.append(challenge_trust)

        if not r.challenge_passed:
            failed_challenges += 1

    base_trust = sum(trust_scores) / len(trust_scores)
    trust_score = base_trust * 100

    if failed_challenges == 1:
        trust_score -= 10
    elif failed_challenges == 2:
        trust_score -= 25
    elif failed_challenges >= 3:
        trust_score -= 40

    trust_score = max(30, min(100, round(trust_score, 2)))

    if trust_score >= 85:
        level = "high"
    elif trust_score >= 60:
        level = "medium"
    else:
        level = "low"

    timestamp = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())

    # -------------------- STORE SESSION IN MEMORY --------------------
    session_log.append({
        "session_id": session_id,
        "device_id": device_id,
        "results": [r.dict() for r in results],
        "trust_score": trust_score,
        "trust_level": level,
        "failed_challenges": failed_challenges,
        "total_challenges": len(results),
        "timestamp_utc": timestamp
    })

    return {
        "trust_score": trust_score,
        "trust_level": level,
        "session_id": session_id,
        "failed_challenges": failed_challenges,
        "total_challenges": len(results),
        "timestamp_utc": timestamp
    }

# -------------------- SESSION LOG VIEW / FILTER --------------------
@app.get("/v1/sessions")
def get_sessions(
    device_id: Optional[str] = Query(None),
    after_ts: Optional[float] = Query(None)
):
    """
    Return session log. Can filter by device_id or sessions after a given timestamp.
    """
    filtered = session_log
    if device_id:
        filtered = [s for s in filtered if s["device_id"] == device_id]
    if after_ts:
        filtered = [s for s in filtered if time.mktime(time.strptime(s["timestamp_utc"], "%Y-%m-%dT%H:%M:%S")) > after_ts]

    return {"sessions": filtered}

# -------------------- SERVE FRONTEND --------------------
@app.get("/")
def read_index():
    return FileResponse("index.html")
