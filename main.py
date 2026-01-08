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

# -------------------- IN-MEMORY SESSION & TRUST STORE --------------------
in_memory_sessions = []
TRUSTED_DEVICES = {}
USED_TOKENS = set()
SERVER_SECRET = "certivo_super_secret"  # move to env later
TRUST_DURATION_SECONDS = 60 * 60 * 24 * 30  # 30 days

# -------------------- GET CHALLENGES --------------------
@app.get("/v1/challenge")
def get_challenge(device_id: str = None, user_agent: str = None):
    """
    Generate challenges for the session.
    Trusted devices may skip some challenges, but at least 1 challenge will always be sent.
    """
    now = time.time()
    record = TRUSTED_DEVICES.get(device_id) if device_id else None
    trusted = False
    if record and record["user_agent"] == user_agent and record["expires_at"] > now:
        trusted = True

    # Determine number of challenges
    challenge_count = 3  # always send 3 for now
    # If we want trusted shortcut later: challenge_count = max(1, 3 if not trusted else 1)

    challenges = generate_challenges(num=challenge_count)

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

    # -------------------- Trusted Device Token for per-challenge verify --------------------
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

# -------------------- FINALIZE SESSION --------------------
@app.post("/v1/finalize")
def finalize_session(payload: dict = Body(...)):
    results = payload.get("results", [])
    device_id = payload.get("device_id", "web")
    user_agent = payload.get("user_agent", "unknown")

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
    session_id = str(uuid.uuid4())
    session_record = {
        "session_id": session_id,
        "device_id": device_id,
        "trust_score": trust_score,
        "trust_level": level,
        "failed_challenges": failed_challenges,
        "total_challenges": len(results),
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
    }

    # -------------------- Trusted Device Token --------------------
    raw = f"{device_id}{user_agent}{session_id}{SERVER_SECRET}"
    token = hashlib.sha256(raw.encode()).hexdigest()
    TRUSTED_DEVICES[device_id] = {
        "trusted_device_token": token,
        "device_id": device_id,
        "user_agent": user_agent,
        "session_id": session_id,
        "issued_at": time.time(),
        "expires_at": time.time() + TRUST_DURATION_SECONDS
    }

    session_record["trusted_device_token"] = token
    session_record["trusted_until"] = TRUSTED_DEVICES[device_id]["expires_at"]

    in_memory_sessions.append(session_record)

    return session_record

# -------------------- REPLAY PROTECTION CHECK --------------------
@app.post("/v1/trusted-check")
def trusted_check(
    trusted_device_token: str = Form(...),
    device_id: str = Form(...),
    user_agent: str = Form(...)
):
    if trusted_device_token in USED_TOKENS:
        return JSONResponse(status_code=403, content={"error": "Replay detected"})

    record = TRUSTED_DEVICES.get(device_id)
    if not record:
        return {"trusted": False}

    if (
        record["trusted_device_token"] != trusted_device_token or
        record["user_agent"] != user_agent or
        record["expires_at"] < time.time()
    ):
        return {"trusted": False}

    USED_TOKENS.add(trusted_device_token)
    return {"trusted": True}

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
