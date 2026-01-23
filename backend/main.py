# main.py — Backend Authority v1 (Certivo)

from fastapi import FastAPI, UploadFile, File, Form, Body, Query, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from datetime import datetime, timedelta
import uuid, os, time, hashlib

from challenge_engine import generate_adaptive_challenges
from human_verification import run_human_verification

app = FastAPI()

# -------------------- CORS --------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

os.makedirs("uploads", exist_ok=True)

# -------------------- IN-MEMORY AUTHORITY STORE (MVP) --------------------

verification_sessions = {}
# session_id → {
#   device_id,
#   status,
#   expires_at,
#   challenges: [ {...} ],
#   current_index
# }

trusted_devices = {}

SESSION_LIFETIME = timedelta(minutes=5)
MAX_RETRIES_PER_CHALLENGE = 2

# -------------------- START SESSION --------------------

@app.post("/v1/start")
def start_verification(device_id: str = Body(...), request: Request = None):
    session_id = str(uuid.uuid4())

    challenges = generate_adaptive_challenges(num=3, trusted=device_id in trusted_devices)

    authoritative_challenges = []
    for idx, ch in enumerate(challenges):
        authoritative_challenges.append({
            "challenge_id": ch["challenge_id"],
            "type": ch["challenge_type"],
            "instruction": ch["challenge_value"],
            "difficulty": ch["difficulty"],
            "order": idx,
            "attempts": 0,
            "max_attempts": MAX_RETRIES_PER_CHALLENGE,
            "passed": False,
            "used": False
        })

    verification_sessions[session_id] = {
        "device_id": device_id,
        "status": "active",
        "created_at": datetime.utcnow(),
        "expires_at": datetime.utcnow() + SESSION_LIFETIME,
        "challenges": authoritative_challenges,
        "current_index": 0
    }

    return {
        "session_id": session_id,
        "challenge": authoritative_challenges[0]
    }

# -------------------- GET CURRENT CHALLENGE --------------------

@app.get("/v1/challenge")
def get_current_challenge(session_id: str = Query(...)):
    session = verification_sessions.get(session_id)

    if not session or session["status"] != "active":
        raise HTTPException(400, "Invalid or inactive session")

    if datetime.utcnow() > session["expires_at"]:
        session["status"] = "expired"
        raise HTTPException(400, "Session expired")

    idx = session["current_index"]
    if idx >= len(session["challenges"]):
        raise HTTPException(400, "No remaining challenges")

    return {
        "session_id": session_id,
        "challenge": session["challenges"][idx]
    }

# -------------------- VERIFY CHALLENGE --------------------

@app.post("/v1/verify")
async def verify_challenge(
    session_id: str = Form(...),
    challenge_id: str = Form(...),
    video: UploadFile = File(...)
):
    session = verification_sessions.get(session_id)

    if not session or session["status"] != "active":
        raise HTTPException(400, "Invalid session")

    idx = session["current_index"]
    challenge = session["challenges"][idx]

    if challenge["challenge_id"] != challenge_id:
        raise HTTPException(403, "Challenge order violation")

    if challenge["used"]:
        raise HTTPException(403, "Challenge already used")

    if challenge["attempts"] >= challenge["max_attempts"]:
        raise HTTPException(403, "Retry limit exceeded")

    video_path = f"uploads/{uuid.uuid4()}_{video.filename}"
    with open(video_path, "wb") as f:
        f.write(video.file.read())

    result = run_human_verification(video_path, None, challenge["type"])

    challenge["attempts"] += 1
    challenge["used"] = True

    if result.get("challenge_passed"):
        challenge["passed"] = True
        session["current_index"] += 1
    else:
        challenge["used"] = False
        if challenge["attempts"] >= challenge["max_attempts"]:
            session["current_index"] += 1

    return {
        "challenge_passed": challenge["passed"],
        "attempts": challenge["attempts"],
        "next_available": session["current_index"] < len(session["challenges"])
    }

# -------------------- FINALIZE --------------------

@app.post("/v1/finalize")
def finalize(session_id: str = Body(...)):
    session = verification_sessions.get(session_id)

    if not session:
        raise HTTPException(400, "Invalid session")

    challenges = session["challenges"]

    passed = sum(1 for c in challenges if c["passed"])
    failed = len(challenges) - passed

    trust_score = max(30, min(100, int((passed / len(challenges)) * 100)))

    trust_level = "high" if trust_score >= 85 else "medium" if trust_score >= 60 else "low"

    if trust_score >= 85:
        token = hashlib.sha256(
            f"{session['device_id']}:{time.time()}".encode()
        ).hexdigest()
        trusted_devices[session["device_id"]] = token

    session["status"] = "completed"

    return {
        "trust_score": trust_score,
        "trust_level": trust_level,
        "passed": passed,
        "failed": failed
    }

# -------------------- FRONTEND --------------------

@app.get("/")
def index():
    return FileResponse("index.html")
