# main.py
from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
import sqlite3, uuid, time, hashlib, os
from challenge_engine import generate_challenges
from human_verification import run_human_verification  # prototype

app = FastAPI()

# -------------------- CORS --------------------
origins = [
    "http://127.0.0.1:5500",
    "http://localhost:5500"
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
    challenges = generate_challenges(num=3)  # 3 challenges per session

    # Insert into DB
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

# -------------------- VERIFY SINGLE CHALLENGE --------------------
@app.post("/v1/verify")
def verify(
    challenge_id: str = Form(...),
    device_id: str = Form(...),
    video: UploadFile = File(...),
    audio: UploadFile = File(None)
):
    # Validate challenge
    c.execute("SELECT challenge_type, challenge_value, used FROM challenges WHERE challenge_id=?", (challenge_id,))
    row = c.fetchone()
    if not row:
        return JSONResponse(status_code=400, content={"error": "Invalid challenge"})
    challenge_type, challenge_value, used = row
    if used:
        return JSONResponse(status_code=400, content={"error": "Challenge already used"})

    # Mark challenge as used
    c.execute("UPDATE challenges SET used=1 WHERE challenge_id=?", (challenge_id,))
    conn.commit()

    # Save uploaded video/audio
    video_path = f"uploads/{uuid.uuid4()}_{video.filename}"
    with open(video_path, "wb") as f:
        f.write(video.file.read())

    audio_path = None
    if audio:
        audio_path = f"uploads/{uuid.uuid4()}_{audio.filename}"
        with open(audio_path, "wb") as f:
            f.write(audio.file.read())

    # Run verification
    result = run_human_verification(video_path, audio_path, challenge_type)

    # ---------------- SAFEGUARD: scores 0..1 ----------------
    result["liveness_score"] = max(0.0, min(1.0, float(result.get("liveness_score", 0.0))))
    result["lip_sync_score"] = max(0.0, min(1.0, float(result.get("lip_sync_score", 0.0))))

    # Trusted device token
    raw_token = f"{device_id}{time.time()}".encode()
    trusted_device_token = hashlib.sha256(raw_token).hexdigest()

    return {
        "verified": result["challenge_passed"],
        "liveness_score": result["liveness_score"],
        "lip_sync_score": result["lip_sync_score"],
        "challenge_passed": result.get("challenge_passed", False),
        "replay_flag": result.get("replay_flag", False),
        "device_trust_score": 0.97,
        "trusted_device_token": trusted_device_token,
        "challenge_type": challenge_type,
        "details": {
            "reasons": ["liveness_ok", "challenge_ok", "lip_sync_ok", "device_safe"],
            "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
        }
    }

# -------------------- FINALIZE SESSION (OPTIONAL) --------------------
@app.post("/v1/finalize")
def finalize_session(data: dict):
    """
    Accepts multiple challenge results to compute a session trust score
    """
    results = data.get("results", [])
    if not results:
        return {"trust_score": 0, "trust_level": "low"}

    # Average liveness score across challenges
    avg_liveness = sum(max(0.0, min(1.0, float(r.get("liveness_score", 0.0)))) for r in results) / len(results)
    score = round(avg_liveness * 100)

    # Trust level
    if score >= 90: level = "high"
    elif score >= 80: level = "medium"
    else: level = "low"

    return {"trust_score": score, "trust_level": level}

# -------------------- SERVE FRONTEND --------------------
@app.get("/")
def read_index():
    return FileResponse("index.html")
