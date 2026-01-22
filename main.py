# main.py — Certivo Prime Robust Flow

from fastapi import FastAPI, UploadFile, File, Form, Query, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlalchemy import create_engine, Column, String, Float, Integer, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime, timedelta
import time, uuid, hashlib, os

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
DATABASE_URL = "sqlite:///./certivo_v2.db"
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

class ChallengeToken(Base):
    __tablename__ = "challenge_tokens"
    token_id = Column(String, primary_key=True, index=True)
    challenge_id = Column(String)
    device_id = Column(String)
    issued_at = Column(DateTime, default=datetime.utcnow)
    used = Column(Integer, default=0)
    max_retries = Column(Integer, default=2)
    retries_done = Column(Integer, default=0)

Base.metadata.create_all(bind=engine)

# -------------------- TRUSTED DEVICES --------------------
trusted_devices = {}  # {device_id: trusted_token}

# -------------------- GET CHALLENGE --------------------
@app.get("/v1/challenge")
async def get_challenge(request: Request, device_id: str = Query(...)):
    user_agent = request.headers.get("user-agent", "unknown")
    db = SessionLocal()
    try:
        # Check session history
        prev_sessions = db.query(SessionRecord).filter(SessionRecord.device_id == device_id).all()
        is_trusted = device_id in trusted_devices

        # Generate challenges
        challenges = generate_adaptive_challenges(prev_results=[], num=3, trusted=is_trusted)

        # Issue tokens for challenges
        tokens = []
        for ch in challenges:
            token_id = str(uuid.uuid4())
            token_record = ChallengeToken(
                token_id=token_id,
                challenge_id=ch["challenge_id"],
                device_id=device_id,
                max_retries=2,
                retries_done=0
            )
            db.add(token_record)
            tokens.append({
                "token_id": token_id,
                "challenge_id": ch["challenge_id"],
                "instruction": ch["challenge_value"],
                "difficulty": ch["difficulty"],
                "fast_track": ch.get("fast_track", False)
            })
        db.commit()
        return {"trusted_device": is_trusted, "challenges": tokens}
    finally:
        db.close()

# -------------------- VERIFY CHALLENGE --------------------
@app.post("/v1/verify")
async def verify(
    request: Request,
    challenge_id: str = Form(...),
    token_id: str = Form(...),
    device_id: str = Form(...),
    video: UploadFile = File(...),
    audio: UploadFile = File(None)
):
    db = SessionLocal()
    try:
        # Validate token
        token = db.query(ChallengeToken).filter(ChallengeToken.token_id == token_id, 
                                                ChallengeToken.device_id == device_id).first()
        if not token:
            raise HTTPException(status_code=400, detail="Invalid challenge token")
        if token.used:
            raise HTTPException(status_code=400, detail="Token already used")
        if token.retries_done >= token.max_retries:
            raise HTTPException(status_code=403, detail="Max retries reached")

        # Save uploads
        video_path = f"uploads/{uuid.uuid4()}_{video.filename}"
        with open(video_path, "wb") as f:
            f.write(video.file.read())

        audio_path = None
        if audio:
            audio_path = f"uploads/{uuid.uuid4()}_{audio.filename}"
            with open(audio_path, "wb") as f:
                f.write(audio.file.read())

        # Run human verification
        result = run_human_verification(video_path, audio_path, challenge_id)
        passed = result.get("challenge_passed", False)

        # Update token status
        if passed:
            token.used = 1
        else:
            token.retries_done += 1
        db.commit()

        return {
            "challenge_passed": passed,
            "liveness_score": result.get("liveness_score", 0),
            "lip_sync_score": result.get("lip_sync_score", 0),
            "reason": result.get("reason", ""),
            "retries_left": token.max_retries - token.retries_done
        }
    finally:
        db.close()

# -------------------- FINALIZE SESSION --------------------
@app.post("/v1/finalize")
async def finalize_session(payload: dict = None):
    if not payload:
        raise HTTPException(status_code=400, detail="No session data provided")
    results = payload.get("results", [])
    device_id = payload.get("device_id", "web")
    user_agent = payload.get("user_agent", "unknown")

    failed_challenges = sum(1 for r in results if not r.get("challenge_passed", False))

    # Compute trust score with penalties for failures and retries
    trust_scores = []
    for r in results:
        liveness = max(0, min(1, r.get("liveness_score", 0)))
        lip_sync = max(0, min(1, r.get("lip_sync_score", 0)))
        trust_scores.append(liveness * 0.5 + lip_sync * 0.5)

    base_trust = sum(trust_scores)/len(trust_scores) if trust_scores else 0
    trust_score = round(max(30, min(100, base_trust*100 - failed_challenges*15)), 2)
    level = "high" if trust_score >= 85 else "medium" if trust_score >= 60 else "low"

    session_id = str(uuid.uuid4())

    db = SessionLocal()
    try:
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
    finally:
        db.close()

    # Mark device trusted if high score
    if trust_score >= 85:
        trusted_devices[device_id] = hashlib.sha256(f"{device_id}:{user_agent}".encode()).hexdigest()

    return {
        "session_id": session_id,
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
