from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from pydantic import BaseModel
from typing import List
import sqlite3, uuid, time, hashlib, os
import numpy as np

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

    # Record timestamp when challenge verification starts
    challenge_start_ts = time.time()

    result = run_human_verification(video_path, audio_path, challenge_type)

    # Record timestamp when challenge verification ends
    challenge_end_ts = time.time()
    reaction_time = challenge_end_ts - challenge_start_ts  # in seconds

    # Metric normalization
    normalized_liveness = max(0.0, min(1.0, result.get("liveness_score", 0)))
    normalized_lip_sync = max(0.0, min(1.0, result.get("lip_sync_score", 0)))
    normalized_reaction_time = min(reaction_time / 10.0, 1.0)  # assuming 10s max for full score

    # Facial stability placeholder (simulate for now)
    facial_stability = np.random.uniform(0.7, 1.0)  # 0–1 scale

    # Blink count placeholder (simulate for now)
    blink_count = np.random.randint(1, 5)

    # Generate a trusted device token
    raw_token = f"{device_id}{time.time()}".encode()
    trusted_device_token = hashlib.sha256(raw_token).hexdigest()

    # Construct session result with metrics
    session_result = {
        "challenge_id": challenge_id,
        "challenge_passed": result["challenge_passed"],
        "liveness_score": normalized_liveness,
        "lip_sync_score": normalized_lip_sync,
        "reaction_time": normalized_reaction_time,
        "facial_stability": facial_stability,
        "blink_count": blink_count,
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
        "trusted_device_token": trusted_device_token,
        "challenge_type": challenge_type
    }

    # Return challenge verification result with metrics
    return session_result

# -------------------- FINALIZE SESSION --------------------
class ChallengeResult(BaseModel):
    liveness_score: float
    lip_sync_score: float
    reaction_time: float
    facial_stability: float
    blink_count: int
    challenge_passed: bool

class FinalizeRequest(BaseModel):
    results: List[ChallengeResult]
    device_id: str

@app.post("/v1/finalize")
def finalize_session(payload: FinalizeRequest):
    results = payload.results

    if not results:
        return {
            "trust_score": 0,
            "trust_level": "low",
            "reason": "no_results"
        }

    # ---------------- AGGREGATE METRICS ----------------
    liveness_scores = [max(0.0, min(1.0, r.liveness_score)) for r in results]
    lip_sync_scores = [max(0.0, min(1.0, r.lip_sync_score)) for r in results]
    reaction_times = [max(0.0, min(1.0, r.reaction_time)) for r in results]
    stability_scores = [max(0.0, min(1.0, r.facial_stability)) for r in results]
    blink_counts = [r.blink_count for r in results]

    failed = sum(1 for r in results if not r.challenge_passed)

    # Weighted aggregation (normalize 0–1, then scale to 0–100)
    aggregated_score = (
        np.mean(liveness_scores) * 0.4 +
        np.mean(lip_sync_scores) * 0.3 +
        np.mean(stability_scores) * 0.2 +
        np.mean([1 - rt for rt in reaction_times]) * 0.1
    ) * 100

    # Soft penalties
    if failed == 1:
        aggregated_score -= 10
    elif failed == 2:
        aggregated_score -= 25
    elif failed >= 3:
        aggregated_score -= 40

    # Clamp
    aggregated_score = max(30, min(100, aggregated_score))
    aggregated_score = round(aggregated_score, 2)

    if aggregated_score >= 85:
        level = "high"
    elif aggregated_score >= 60:
        level = "medium"
    else:
        level = "low"

    return {
        "trust_score": aggregated_score,
        "trust_level": level,
        "failed_challenges": failed,
        "total_challenges": len(results),
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
    }

# -------------------- SERVE FRONTEND --------------------
@app.get("/")
def read_index():
    return FileResponse("index.html")
