from fastapi import FastAPI, UploadFile, File, Form, Body, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Dict, List
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

# -------------------- STORAGE --------------------
os.makedirs("uploads", exist_ok=True)

# Active sessions (analytics + replay protection)
SESSIONS: Dict[str, dict] = {}

# Trusted devices (device_hash → metadata)
TRUSTED_DEVICES: Dict[str, dict] = {}

# -------------------- HELPERS --------------------
def device_hash(device_id: str, user_agent: str) -> str:
    return hashlib.sha256(f"{device_id}:{user_agent}".encode()).hexdigest()

# -------------------- START VERIFICATION --------------------
class StartVerification(BaseModel):
    device_id: str
    user_agent: str

@app.post("/v1/start-verification")
async def start_verification(data: StartVerification):
    d_hash = device_hash(data.device_id, data.user_agent)

    # 🔐 Trusted shortcut
    if d_hash in TRUSTED_DEVICES:
        trusted = TRUSTED_DEVICES[d_hash]
        return {
            "trusted": True,
            "verdict": "HUMAN VERIFIED",
            "confidence": trusted["confidence"]
        }

    # New session
    session_id = str(uuid.uuid4())
    SESSIONS[session_id] = {
        "session_id": session_id,
        "device_id": data.device_id,
        "user_agent": data.user_agent,
        "started_at": time.time(),
        "results": [],
        "completed": False
    }

    return {
        "trusted": False,
        "session_id": session_id
    }

# -------------------- GET CHALLENGES --------------------
@app.get("/v1/challenge")
async def get_challenge(session_id: str = Query(...)):
    session = SESSIONS.get(session_id)
    if not session:
        return {"error": "Invalid session"}

    challenges = generate_challenges(num=3)
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
async def verify(
    request: Request,
    session_id: str = Form(...),
    challenge_id: str = Form(...),
    video: UploadFile = File(...),
    audio: UploadFile = File(None)
):
    session = SESSIONS.get(session_id)
    if not session or session["completed"]:
        return {"error": "Invalid or closed session"}

    video_path = f"uploads/{uuid.uuid4()}_{video.filename}"
    with open(video_path, "wb") as f:
        f.write(video.file.read())

    audio_path = None
    if audio:
        audio_path = f"uploads/{uuid.uuid4()}_{audio.filename}"
        with open(audio_path, "wb") as f:
            f.write(audio.file.read())

    result = run_human_verification(video_path, audio_path, "generic")

    session["results"].append({
        "challenge_id": challenge_id,
        "challenge_passed": result.get("challenge_passed", False),
        "liveness_score": result.get("liveness_score", 0),
        "lip_sync_score": result.get("lip_sync_score", 0),
        "reaction_time": result.get("reaction_time", 1.0),
        "facial_stability": result.get("facial_stability", 1.0),
        "blink_count": result.get("blink_count", 0),
        "timestamp": time.time()
    })

    return {"status": "recorded"}

# -------------------- FINALIZE SESSION --------------------
@app.post("/v1/finalize")
async def finalize(payload: dict = Body(...)):
    session_id = payload.get("session_id")
    session = SESSIONS.get(session_id)

    if not session or session["completed"]:
        return {"error": "Invalid session"}

    results = session["results"]
    if not results:
        return {"error": "No challenges completed"}

    scores = []
    failed = 0

    for r in results:
        liveness = r["liveness_score"]
        lip = r["lip_sync_score"]
        reaction = max(0, 1 - r["reaction_time"])
        stability = r["facial_stability"]
        blink_penalty = max(0, (r["blink_count"] - 5) * 0.02)

        score = (
            liveness * 0.35 +
            lip * 0.25 +
            reaction * 0.15 +
            stability * 0.15 -
            blink_penalty
        )

        scores.append(score)
        if not r["challenge_passed"]:
            failed += 1

    trust_score = round(max(0, min(100, (sum(scores) / len(scores)) * 100)), 2)

    if failed >= 2:
        trust_score -= 25

    verdict = "HUMAN VERIFIED" if trust_score >= 60 else "LOW TRUST"

    # 🔐 Trust device if strong pass
    if trust_score >= 85:
        d_hash = device_hash(session["device_id"], session["user_agent"])
        TRUSTED_DEVICES[d_hash] = {
            "confidence": trust_score,
            "trusted_at": time.time()
        }

    session["completed"] = True
    session["trust_score"] = trust_score
    session["verdict"] = verdict

    return {
        "verdict": verdict,
        "trust_score": trust_score
    }

# -------------------- ANALYTICS --------------------
@app.get("/v1/sessions")
async def sessions(device_id: str = Query(None)):
    data = list(SESSIONS.values())
    if device_id:
        data = [s for s in data if s["device_id"] == device_id]
    return {"sessions": data}

# -------------------- SERVE FRONTEND --------------------
@app.get("/")
def index():
    return FileResponse("index.html")
