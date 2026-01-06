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
        "replay_flag": result.get("replay_flag", False),
        "trusted_device_token": trusted_device_token,
        "challenge_type": challenge_type,
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
    }

# -------------------- FINALIZE SESSION --------------------

class ChallengeResult(BaseModel):
    liveness_score: float
    lip_sync_score: float
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

    liveness_scores = []
    failed = 0

    for r in results:
        score = max(0.0, min(1.0, r.liveness_score))
        liveness_scores.append(score)

        if not r.challenge_passed:
            failed += 1

    # Average liveness
    base_trust = sum(liveness_scores) / len(liveness_scores)
    trust_score = base_trust * 100

    # Soft penalties (V1 logic)
    if failed == 1:
        trust_score -= 10
    elif failed == 2:
        trust_score -= 25
    elif failed >= 3:
        trust_score -= 40

    # Human floor & clamp
    trust_score = max(30, trust_score)
    trust_score = min(100, trust_score)
    trust_score = round(trust_score, 2)

    if trust_score >= 85:
        level = "high"
    elif trust_score >= 60:
        level = "medium"
    else:
        level = "low"

    return {
        "trust_score": trust_score,
        "trust_level": level,
        "failed_challenges": failed,
        "total_challenges": len(results),
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
    }

# -------------------- SERVE FRONTEND --------------------
@app.get("/")
def read_index():
    return FileResponse("index.html")
