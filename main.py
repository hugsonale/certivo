# main.py
from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
import sqlite3, uuid, time, hashlib, os
from typing import List

from challenge_engine import generate_challenges
from human_verification import run_human_verification  # prototype

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

# -------------------- GET MULTIPLE CHALLENGES --------------------
@app.get("/v1/challenge")
def get_challenge():
    challenges = generate_challenges(num=3)

    for ch in challenges:
        c.execute(
            "INSERT INTO challenges VALUES (?, ?, ?, ?, 0)",
            (ch["challenge_id"], ch["challenge_type"], ch["challenge_value"], time.time())
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

# -------------------- VERIFY (PER CHALLENGE) --------------------
@app.post("/v1/verify")
def verify(
    challenge_id: str = Form(...),
    device_id: str = Form(...),
    video: UploadFile = File(...),
    audio: UploadFile = File(None)
):
    c.execute(
        "SELECT challenge_type, challenge_value, used FROM challenges WHERE challenge_id=?",
        (challenge_id,)
    )
    row = c.fetchone()

    if not row:
        return JSONResponse(status_code=400, content={"error": "Invalid challenge"})

    challenge_type, challenge_value, used = row
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

    # Run prototype human verification
    result = run_human_verification(video_path, audio_path, challenge_type)

    # Reaction time simulation (V1 placeholder)
    response_time = round(result.get("response_time", 1.5), 2)

    # Trusted device token (V1 – not persistent yet)
    raw_token = f"{device_id}{time.time()}".encode()
    trusted_device_token = hashlib.sha256(raw_token).hexdigest()

    return {
        "challenge_passed": result.get("challenge_passed", False),
        "face_stability": round(result.get("face_stability", 0.9), 2),
        "response_time": response_time,
        "replay_flag": result.get("replay_flag", False),
        "trusted_device_token": trusted_device_token
    }

# -------------------- FINALIZE SESSION --------------------
@app.post("/v1/finalize")
def finalize_session(payload: dict):
    results: List[dict] = payload.get("results", [])
    device_id = payload.get("device_id")

    if not results:
        return JSONResponse(status_code=400, content={"error": "No session results"})

    total = len(results)
    passed = sum(1 for r in results if r.get("challenge_passed"))
    pass_rate = passed / total

    avg_response = sum(r.get("response_time", 2) for r in results) / total
    avg_stability = sum(r.get("face_stability", 0.8) for r in results) / total

    # --------------------
    # TRUST SCORE (V1)
    # --------------------
    score = (
        pass_rate * 40 +
        (1 - min(avg_response / 5, 1)) * 25 +
        avg_stability * 35
    ) * 100

    trust_score = round(score)

    if trust_score >= 90:
        trust_level = "high"
    elif trust_score >= 70:
        trust_level = "medium"
    else:
        trust_level = "low"

    return {
        "human_verified": trust_score >= 70,
        "trust_score": trust_score,
        "trust_level": trust_level,
        "summary": {
            "challenges_completed": total,
            "pass_rate": round(pass_rate, 2),
            "avg_response_time": round(avg_response, 2),
            "avg_face_stability": round(avg_stability, 2)
        },
        "issued_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
    }

# -------------------- SERVE FRONTEND --------------------
@app.get("/")
def read_index():
    """
    Serve the frontend HTML directly from FastAPI.
    Open http://127.0.0.1:8000/ in your browser.
    """
    return FileResponse("index.html")
