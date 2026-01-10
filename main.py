from fastapi import FastAPI, UploadFile, File, Form, Body, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from pydantic import BaseModel
from typing import List
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

# -------------------- DATABASE (for challenges only) --------------------
os.makedirs("uploads", exist_ok=True)

# -------------------- IN-MEMORY SESSION & TRUSTED DEVICE STORE --------------------
in_memory_sessions = []
trusted_devices = {}  # {device_id: trusted_token}

# -------------------- GET CHALLENGES --------------------
@app.get("/v1/challenge")
async def get_challenge(request: Request, device_id: str = Query(...)):
    # Check if device is trusted
    user_agent = request.headers.get("user-agent", "unknown")
    trusted_token = trusted_devices.get(device_id)
    if trusted_token:
        # Already trusted: return minimal challenge
        challenge = generate_challenges(num=1)[0]
        return {
            "trusted_device": True,
            "challenges": [{
                "challenge_id": challenge["challenge_id"],
                "challenge_type": challenge["challenge_type"],
                "instruction": challenge["challenge_value"],
                "expires_in": 60
            }]
        }

    # Not trusted: normal challenge flow
    challenges = generate_challenges(num=3)
    return {
        "trusted_device": False,
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
async def verify(
    request: Request,
    challenge_id: str = Form(...),
    device_id: str = Form(...),
    video: UploadFile = File(...),
    audio: UploadFile = File(None)
):
    video_path = f"uploads/{uuid.uuid4()}_{video.filename}"
    with open(video_path, "wb") as f:
        f.write(video.file.read())

    audio_path = None
    if audio:
        audio_path = f"uploads/{uuid.uuid4()}_{audio.filename}"
        with open(audio_path, "wb") as f:
            f.write(audio.file.read())

    result = run_human_verification(video_path, audio_path, "generic")  # challenge_type could be extended

    # Trusted device token
    user_agent = request.headers.get("user-agent", "unknown")
    raw_token = f"{device_id}:{user_agent}:{uuid.uuid4()}".encode()
    trusted_device_token = hashlib.sha256(raw_token).hexdigest()

    return {
        "challenge_passed": result.get("challenge_passed", False),
        "liveness_score": result.get("liveness_score", 0),
        "lip_sync_score": result.get("lip_sync_score", 0),
        "reaction_time": result.get("reaction_time", 1.0),
        "facial_stability": result.get("facial_stability", 1.0),
        "blink_count": result.get("blink_count", 0),
        "replay_flag": False,
        "trusted_device_token": trusted_device_token,
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
    }

# -------------------- FINALIZE SESSION --------------------
@app.post("/v1/finalize")
async def finalize_session(payload: dict = Body(...)):
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

        if failed_challenges == 1:
            trust_score -= 10
        elif failed_challenges == 2:
            trust_score -= 25
        elif failed_challenges >= 3:
            trust_score -= 40
        trust_score = max(30, trust_score)

        if trust_score >= 85:
            level = "high"
        elif trust_score >= 60:
            level = "medium"
        else:
            level = "low"

    # Store session in memory
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

    # If score high enough, mark device as trusted
    if trust_score >= 85:
        trusted_token = hashlib.sha256(f"{device_id}:{user_agent}:{session_record['session_id']}".encode()).hexdigest()
        trusted_devices[device_id] = trusted_token
        session_record["trusted_device_token"] = trusted_token

    return session_record

# -------------------- SESSIONS LIST FOR ANALYTICS --------------------
@app.get("/v1/sessions")
async def get_sessions(device_id: str = Query(None), after_ts: float = Query(None)):
    filtered = in_memory_sessions
    if device_id:
        filtered = [s for s in filtered if s["device_id"] == device_id]
    if after_ts:
        filtered = [s for s in filtered if time.mktime(time.strptime(s["timestamp_utc"], "%Y-%m-%dT%H:%M:%S")) > after_ts]
    return {"sessions": filtered}

# -------------------- SERVE FRONTEND --------------------
@app.get("/")
def read_index():
    return FileResponse("index.html")
