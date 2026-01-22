# main.py

from fastapi import FastAPI, UploadFile, File, Form, Body, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlalchemy import create_engine, Column, String, Float, Integer, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime
import time, uuid, hashlib, os
import cv2

from challenge_engine import generate_adaptive_challenges
from human_verification import run_human_verification

# -------------------- FASTAPI APP --------------------
app = FastAPI()

origins = ["http://127.0.0.1:5500", "http://localhost:5500", "http://127.0.0.1:8000"]

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

# -------------------- TRUSTED DEVICES --------------------
trusted_devices = {}  # {device_id: trusted_token}

# -------------------- FACE VERIFICATION --------------------
@app.post("/v1/face_verify")
async def face_verify(device_id: str = Form(...), face_image: UploadFile = File(...)):
    path = f"uploads/{uuid.uuid4()}_{face_image.filename}"
    with open(path, "wb") as f:
        f.write(face_image.file.read())

    img = cv2.imread(path)
    if img is None:
        os.remove(path)
        return {"verified": False}

    face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    faces = face_cascade.detectMultiScale(gray, 1.3, 5)
    os.remove(path)
    return {"verified": len(faces) == 1}

# -------------------- GET CHALLENGE --------------------
@app.get("/v1/challenge")
async def get_challenge(request: Request, device_id: str = Query(...)):
    user_agent = request.headers.get("user-agent", "unknown")
    is_trusted = device_id in trusted_devices

    db = SessionLocal()
    prev_sessions = db.query(SessionRecord).filter(SessionRecord.device_id == device_id).all()
    db.close()

    prev_results = []  # placeholder
    challenges = generate_adaptive_challenges(prev_results=prev_results, num=3, trusted=is_trusted)

    normalized = []
    for ch in challenges:
        # Generate server-side token for each challenge
        challenge_token = hashlib.sha256(f"{device_id}:{ch['challenge_id']}".encode()).hexdigest()
        normalized.append({
            "id": ch["challenge_id"],
            "token": challenge_token,
            "type": ch.get("challenge_type"),
            "instruction": ch.get("challenge_value"),
            "time_limit": 7,
            "difficulty": ch.get("difficulty", "medium"),
            "fast_track": is_trusted
        })

    return {"trusted_device": is_trusted, "challenges": normalized}

# -------------------- VERIFY CHALLENGE --------------------
@app.post("/v1/verify")
async def verify(
    request: Request,
    challenge_id: str = Form(...),
    challenge_token: str = Form(...),
    device_id: str = Form(...),
    video: UploadFile = File(...),
    audio: UploadFile = File(None)
):
    # Enforce token
    expected_token = hashlib.sha256(f"{device_id}:{challenge_id}".encode()).hexdigest()
    if challenge_token != expected_token:
        return {"challenge_passed": False, "reason": "invalid_token"}

    video_path = f"uploads/{uuid.uuid4()}_{video.filename}"
    with open(video_path, "wb") as f:
        f.write(video.file.read())

    audio_path = None
    if audio:
        audio_path = f"uploads/{uuid.uuid4()}_{audio.filename}"
        with open(audio_path, "wb") as f:
            f.write(audio.file.read())

    result = run_human_verification(video_path, audio_path, "generic")

    # NO default pass
    if "challenge_passed" not in result:
        result["challenge_passed"] = False

    return result

# -------------------- FINALIZE SESSION --------------------
@app.post("/v1/finalize")
async def finalize_session(payload: dict = Body(...)):
    results = payload.get("results", [])
    device_id = payload.get("device_id", "web")
    user_agent = payload.get("user_agent", "unknown")

    trust_scores = []
    failed_challenges = 0

    for r in results:
        liveness = max(0, min(1, r.get("liveness_score", 0)))
        lip_sync = max(0, min(1, r.get("lip_sync_score", 0)))
        reaction_time = max(0, min(1, r.get("reaction_time", 1)))
        stability = max(0, min(1, r.get("facial_stability", 1)))
        blink_count = r.get("blink_count", 0)
        difficulty = r.get("difficulty", "medium")

        weight = {"easy": 0.8, "medium": 1.0, "hard": 1.2}.get(difficulty, 1.0)
        blink_penalty = min(max(blink_count - 5, 0) * 0.02, 0.2)

        score = (liveness*0.35 + lip_sync*0.25 + reaction_time*0.15 + stability*0.15 - blink_penalty)*weight
        trust_scores.append(score)

        if not r.get("challenge_passed", True):
            failed_challenges += 1

    base_trust = sum(trust_scores)/len(trust_scores) if trust_scores else 0
    trust_score = round(max(30,min(100,base_trust*100)),2)

    if failed_challenges == 1: trust_score -= 10
    elif failed_challenges == 2: trust_score -= 25
    elif failed_challenges >=3: trust_score -=40

    trust_score = max(30, trust_score)
    level = "high" if trust_score>=85 else "medium" if trust_score>=60 else "low"

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

    if trust_score >=85:
        trusted_devices[device_id] = hashlib.sha256(f"{device_id}:{user_agent}".encode()).hexdigest()

    return {
        "session_id": session_id,
        "device_id": device_id,
        "trust_score": trust_score,
        "trust_level": level,
        "failed_challenges": failed_challenges,
        "total_challenges": len(results),
        "timestamp_utc": datetime.utcnow()
    }

# -------------------- SERVE FRONTEND --------------------
@app.get("/")
def read_index():
    return FileResponse("index.html")
