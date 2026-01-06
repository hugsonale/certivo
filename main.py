from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from pydantic import BaseModel
from typing import List
import sqlite3, uuid, time, hashlib, os

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

# -------------------- DATABASE --------------------
DB = "certivo.db"
os.makedirs("uploads", exist_ok=True)

conn = sqlite3.connect(DB, check_same_thread=False)
c = conn.cursor()

c.execute("""
CREATE TABLE IF NOT EXISTS challenges (
    challenge_id TEXT PRIMARY KEY,
    challenge_type TEXT,
    challenge_value TEXT,
    created_at REAL,
    used INTEGER DEFAULT 0
)
""")
conn.commit()

# -------------------- GET CHALLENGES --------------------
@app.get("/v1/challenge")
def get_challenge():
    challenges = generate_challenges(num=3)

    for ch in challenges:
        c.execute(
            "INSERT INTO challenges VALUES (?, ?, ?, ?, 0)",
            (
                ch["challenge_id"],
                ch["challenge_type"],
                ch["challenge_value"],
                time.time()
            )
        )
    conn.commit()

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

# -------------------- VERIFY CHALLENGE --------------------
@app.post("/v1/verify")
def verify(
    challenge_id: str = Form(...),
    device_id: str = Form(...),
    video: UploadFile = File(...),
    audio: UploadFile = File(None)
):
    c.execute(
        "SELECT challenge_type, used FROM challenges WHERE challenge_id=?",
        (challenge_id,)
    )
    row = c.fetchone()

    if not row:
        return JSONResponse(status_code=400, content={"error": "Invalid challenge"})

    challenge_type, used = row
    if used:
        return JSONResponse(status_code=400, content={"error": "Challenge already used"})

    c.execute("UPDATE challenges SET used=1 WHERE challenge_id=?", (challenge_id,))
    conn.commit()

    video_path = f"uploads/{uuid.uuid4()}_{video.filename}"
    with open(video_path, "wb") as f:
        f.write(video.file.read())

    audio_path = None
    if audio:
        audio_path = f"uploads/{uuid.uuid4()}_{audio.filename}"
        with open(audio_path, "wb") as f:
            f.write(audio.file.read())

    result = run_human_verification(video_path, audio_path, challenge_type)

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
        "challenge_type": challenge_type,
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
    }



@app.post("/v1/finalize")
def finalize_session(payload: dict):
    """
    Aggregates all session metrics (liveness, lip sync, reaction, blink, stability)
    and computes a normalized trust score (0-100)
    """
    results = payload.get("results", [])
    device_id = payload.get("device_id", "web")

    if not results:
        return {"trust_score": 0, "trust_level": "low", "details": "No challenge results"}

    # Normalize and combine metrics
    combined_scores = []
    for r in results:
        # Normalize each metric
        liveness = max(0, min(1, r.get("liveness_score", 0)))
        lip_sync = max(0, min(1, r.get("lip_sync_score", 0)))
        stability = max(0, min(1, r.get("stability_score", 0)))
        reaction = 1 / (1 + r.get("reaction_time", 1))  # faster = closer to 1
        blink = max(0, min(1, r.get("blink_count", 0)/5)) # assume max 5 blinks per challenge

        # Weighted combination
        trust = (
            0.3*liveness +
            0.2*lip_sync +
            0.2*stability +
            0.2*reaction +
            0.1*blink
        )
        combined_scores.append(trust)

    # Aggregate session
    aggregated_score = sum(combined_scores) / len(combined_scores)
    aggregated_score *= 100
    aggregated_score = round(max(0, min(aggregated_score, 100)), 2)

    # Determine trust level
    if aggregated_score >= 85:
        trust_level = "high"
    elif aggregated_score >= 60:
        trust_level = "medium"
    else:
        trust_level = "low"

    return {
        "trust_score": aggregated_score,
        "trust_level": trust_level,
        "device_id": device_id,
        "total_challenges": len(results),
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
    }




# -------------------- FINALIZE SESSION (V2 METRICS) --------------------
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
    if not results:
        return {
            "trust_score": 0,
            "trust_level": "low",
            "reason": "no_results"
        }

    # -------------------- NORMALIZE METRICS --------------------
    trust_scores = []
    failed_challenges = 0

    for r in results:
        # Clamp scores between 0 and 1
        liveness = max(0, min(1, r.liveness_score))
        lip_sync = max(0, min(1, r.lip_sync_score))
        reaction_time = max(0, min(1, r.reaction_time))
        stability = max(0, min(1, r.facial_stability))

        # Blink penalty: more than 5 blinks per challenge reduces trust slightly
        blink_penalty = 0
        if r.blink_count > 5:
            blink_penalty = min((r.blink_count - 5) * 0.02, 0.2)  # max 0.2 reduction

        # Aggregate per-challenge trust (weights adjustable)
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

    # -------------------- AGGREGATE ACROSS SESSION --------------------
    base_trust = sum(trust_scores) / len(trust_scores)  # 0-1
    trust_score = base_trust * 100

    # -------------------- SOFT PENALTIES FOR FAILED CHALLENGES --------------------
    if failed_challenges == 1:
        trust_score -= 10
    elif failed_challenges == 2:
        trust_score -= 25
    elif failed_challenges >= 3:
        trust_score -= 40

    # Clamp final score
    trust_score = max(30, min(100, round(trust_score, 2)))

    # -------------------- TRUST LEVEL --------------------
    if trust_score >= 85:
        level = "high"
    elif trust_score >= 60:
        level = "medium"
    else:
        level = "low"

    return {
        "trust_score": trust_score,
        "trust_level": level,
        "failed_challenges": failed_challenges,
        "total_challenges": len(results),
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
    }

# -------------------- SERVE FRONTEND --------------------
@app.get("/")
def read_index():
    return FileResponse("index.html")
