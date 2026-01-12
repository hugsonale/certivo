# main.py

from fastapi import FastAPI, UploadFile, File, Form, Body, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlalchemy import create_engine, Column, String, Float, Integer, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime
import time, uuid, hashlib, os

from challenge_engine import generate_adaptive_challenges
from human_verification import run_human_verification

# -------------------- FASTAPI APP --------------------
app = FastAPI()

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

# -------------------- SQLITE / SQLALCHEMY --------------------
DATABASE_URL = "sqlite:///./certivo_v1.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()

class SessionRecord(Base):
    __tablename__ = "sessions"
    session_id = Column(String, primary_key=True, index=True)
    device_id = Column(String)
    trust_score = Column(Float)
    trust_level = Column(String)
    failed_challenges = Column(Integer)
    total_challenges = Column(Integer)
    timestamp_utc = Column(DateTime, default=datetime.utcnow)

Base.metadata.create_all(bind=engine)

# -------------------- IN-MEMORY TRUSTED DEVICE STORE --------------------
trusted_devices = {}  # {device_id: trusted_token}

# -------------------- GET CHALLENGE --------------------
@app.get("/v1/challenge")
async def get_challenge(request: Request, device_id: str = Query(...)):
    """
    Phase 3.8 – Adaptive challenge fetching
    Returns multiple normalized challenges (frontend-safe)
    """

    user_agent = request.headers.get("user-agent", "unknown")
    is_trusted = device_id in trusted_devices

    # Fetch previous sessions (future adaptive use)
    db = SessionLocal()
    prev_sessions = db.query(SessionRecord).filter(
        SessionRecord.device_id == device_id
    ).all()
    db.close()

    prev_results = []  # placeholder for now

    # Generate multiple adaptive challenges
    challenges = generate_adaptive_challenges(
        prev_results=prev_results,
        num=3,          # 3 challenges per session
        trusted=is_trusted
    )

    # Safety check
    if not challenges or not isinstance(challenges, list):
        return {
            "trusted_device": is_trusted,
            "challenges": [],
            "error": "No challenges generated"
        }

    # Normalize all challenges
    normalized_challenges = []
    for ch in challenges:
        normalized_challenges.append({
            "id": ch.get("challenge_id"),
            "type": ch.get("challenge_type"),
            "instruction": ch.get("challenge_value"),
            "time_limit": 7,
            "difficulty": ch.get("difficulty", "medium")
        })

    return {
        "trusted_device": is_trusted,
        "challenges": normalized_challenges
    }


# -------------------- VERIFY CHALLENGE --------------------
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

    # Run human verification
    result = run_human_verification(video_path, audio_path, "generic")

    # Ensure the challenge_passed key always exists
    if "challenge_passed" not in result:
        result["challenge_passed"] = True

    # Return normalized response
    return {
        "liveness_score": result.get("liveness_score", 0),
        "lip_sync_score": result.get("lip_sync_score", 0),
        "reaction_time": result.get("reaction_time", 1.0),
        "facial_stability": result.get("facial_stability", 1.0),
        "blink_count": result.get("blink_count", 0),
        "challenge_passed": result.get("challenge_passed", True),
        "replay_flag": False,
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
    }


# -------------------- FINALIZE SESSION --------------------
@app.post("/v1/finalize")
async def finalize_session(payload: dict = Body(...)):
    results = payload.get("results", [])
    device_id = payload.get("device_id", "web")
    user_agent = payload.get("user_agent", "unknown")

    trust_scores = []
    failed_challenges = 0

    total_liveness = 0
    total_reaction = 0
    total_stability = 0

    for r in results:
        liveness = max(0, min(1, r.get("liveness_score", 0)))
        lip_sync = max(0, min(1, r.get("lip_sync_score", 0)))
        reaction_time = max(0, min(1, r.get("reaction_time", 1)))
        stability = max(0, min(1, r.get("facial_stability", 1)))
        blink_count = r.get("blink_count", 0)
        difficulty = r.get("difficulty", "medium")

        weight = {"easy": 0.8, "medium": 1.0, "hard": 1.2}.get(difficulty, 1.0)
        blink_penalty = min(max(blink_count - 5, 0) * 0.02, 0.2)

        score = (
            liveness * 0.35 +
            lip_sync * 0.25 +
            reaction_time * 0.15 +
            stability * 0.15 -
            blink_penalty
        ) * weight

        trust_scores.append(score)

        total_liveness += liveness
        total_reaction += reaction_time
        total_stability += stability

        if not r.get("challenge_passed", True):
            failed_challenges += 1

    base_trust = sum(trust_scores) / len(trust_scores) if trust_scores else 0
    trust_score = round(max(30, min(100, base_trust * 100)), 2)

    if failed_challenges == 1:
        trust_score -= 10
    elif failed_challenges == 2:
        trust_score -= 25
    elif failed_challenges >= 3:
        trust_score -= 40

    trust_score = max(30, trust_score)

    level = "high" if trust_score >= 85 else "medium" if trust_score >= 60 else "low"

    session_id = str(uuid.uuid4())

    db = SessionLocal()
    db.merge(SessionRecord(
        session_id=session_id,
        device_id=device_id,
        trust_score=trust_score,
        trust_level=level,
        failed_challenges=failed_challenges,
        total_challenges=len(results),
        timestamp_utc=datetime.utcnow()
    ))
    db.commit()
    db.close()

    if trust_score >= 85:
        trusted_devices[device_id] = hashlib.sha256(
            f"{device_id}:{user_agent}".encode()
        ).hexdigest()

    return {
        "session_id": session_id,
        "device_id": device_id,
        "trust_score": trust_score,
        "trust_level": level,
        "failed_challenges": failed_challenges,
        "total_challenges": len(results),
        "timestamp_utc": datetime.utcnow()
    }

# -------------------- ANALYTICS --------------------
@app.get("/v1/sessions")
async def get_sessions(device_id: str = Query(None)):
    db = SessionLocal()
    query = db.query(SessionRecord)
    if device_id:
        query = query.filter(SessionRecord.device_id == device_id)
    sessions = query.all()
    db.close()

    return {
        "sessions": [
            {
                "session_id": s.session_id,
                "device_id": s.device_id,
                "trust_score": s.trust_score,
                "trust_level": s.trust_level,
                "failed_challenges": s.failed_challenges,
                "total_challenges": s.total_challenges,
                "timestamp_utc": s.timestamp_utc.strftime("%Y-%m-%dT%H:%M:%S")
            }
            for s in sessions
        ]
    }

# -------------------- SERVE FRONTEND --------------------
@app.get("/")
def read_index():
    return FileResponse("index.html")
