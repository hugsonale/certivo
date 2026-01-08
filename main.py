from fastapi import FastAPI, UploadFile, File, Form, Body, Query
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

# -------------------- DATABASE (for challenges only) --------------------
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

# -------------------- IN-MEMORY SESSION STORE --------------------
in_memory_sessions = []

# -------------------- TRUSTED DEVICES STORE --------------------
TRUSTED_DEVICES = {}  # device_id -> {token, user_agent, expires_at}
TRUSTED_DURATION = 24 * 60 * 60  # 24 hours

# -------------------- GET CHALLENGES --------------------
@app.get("/v1/challenge")
def get_challenge(device_id: str = Query(...), user_agent: str = Query(...)):
    """
    Returns challenges. If device is trusted and token valid, reduce challenges.
    """
    now = time.time()
    # check if trusted
    trusted = False
    if device_id in TRUSTED_DEVICES:
        info = TRUSTED_DEVICES[device_id]
        if info["expires_at"] > now and info["user_agent"] == user_agent:
            trusted = True

    num_challenges = 1 if trusted else 3
    challenges = generate_challenges(num=num_challenges)

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
        ],
        "trusted_device": trusted
    }

# -------------------- VERIFY CHALLENGE --------------------
@app.post("/v1/verify")
def verify(
    challenge_id: str = Form(...),
    device_id: str = Form(...),
    user_agent: str = Form(...),
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

    trusted_device_token = None
    if result.get("challenge_passed", False):
        # Generate token
        raw_token = f"{device_id}{user_agent}{time.time()}".encode()
        trusted_device_token = hashlib.sha256(raw_token).hexdigest()
        # Store device as trusted
        TRUSTED_DEVICES[device_id] = {
            "token": trusted_device_token,
            "user_agent": user_agent,
            "expires_at": time.time() + TRUSTED_DURATION
        }

    return {
        "challenge_passed": result.get("challenge_passed", False),
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

# -------------------- FINALIZE SESSION --------------------
@app.post("/v1/finalize")
def finalize_session(payload: dict = Body(...)):
    results = payload.get("results", [])
    device_id = payload.get("device_id", "web")

    if not results:
        trust_score = 0
        level = "low"
        failed_challenges = 0
    else:
        trust_scores = []
        failed_challenges = 0

        for r in results:
            liveness = max(0, min(1, r.get("liveness_score", 0)))
            lip_sync = max(0, min(1, r.get("lip_sync_score", 0)))
            reaction_time = max(0, min(1, r.get("reaction_time", 1)))
            stability = max(0, min(1, r.get("facial_stability", 1)))
            blink_count = r.get("blink_count", 0)

            blink_penalty = 0
            if blink_count > 5:
                blink_penalty = min((blink_count - 5) * 0.02, 0.2)

            challenge_trust = (
                liveness * 0.35 +
                lip_sync * 0.25 +
                reaction_time * 0.15 +
                stability * 0.15 -
                blink_penalty
            )
            trust_scores.append(challenge_trust)

            if not r.get("challenge_passed", True):
                failed_challenges += 1

        base_trust = sum(trust_scores) / len(trust_scores)
        trust_score = round(max(30, min(100, base_trust * 100)), 2)

        # Soft penalties for failed challenges
        if failed_challenges == 1:
            trust_score -= 10
        elif failed_challenges == 2:
            trust_score -= 25
        elif failed_challenges >= 3:
            trust_score -= 40
        trust_score = max(30, trust_score)

        # Trust level
        if trust_score >= 85:
            level = "high"
        elif trust_score >= 60:
            level = "medium"
        else:
            level = "low"

    # -------------------- STORE SESSION IN MEMORY --------------------
    session_record = {
        "session_id": str(uuid.uuid4()),
        "device_id": device_id,
        "trust_score": trust_score,
        "trust_level": level,
        "failed_challenges": failed_challenges,
        "total_challenges": len(results),
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
    }
    in_memory_sessions.append(session_record)

    return session_record

# -------------------- SESSIONS LIST FOR ANALYTICS --------------------
@app.get("/v1/sessions")
def get_sessions(
    device_id: str = Query(None),
    after_ts: float = Query(None)  # UNIX timestamp
):
    filtered = in_memory_sessions

    if device_id:
        filtered = [s for s in filtered if s["device_id"] == device_id]

    if after_ts:
        filtered = [
            s for s in filtered 
            if time.mktime(time.strptime(s["timestamp_utc"], "%Y-%m-%dT%H:%M:%S")) > after_ts
        ]

    return {"sessions": filtered}

# -------------------- SERVE FRONTEND --------------------
@app.get("/")
def read_index():
    return FileResponse("index.html")
