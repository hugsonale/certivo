from fastapi import FastAPI, UploadFile, File, Form, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
import sqlite3, uuid, time, hashlib, os
from challenge_engine import generate_challenges
from human_verification import run_human_verification

app = FastAPI()

# -------------------- CORS --------------------
origins = ["http://127.0.0.1:5500", "http://localhost:5500"]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])

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
    challenges = generate_challenges(num=3)
    for ch in challenges:
        c.execute("INSERT INTO challenges VALUES (?,?,?,?,0)",
                  (ch["challenge_id"], ch["challenge_type"], ch["challenge_value"], time.time()))
    conn.commit()
    return {"challenges":[
        {"challenge_id":ch["challenge_id"], "challenge_type":ch["challenge_type"],
         "instruction":ch["challenge_value"], "expires_in":60} for ch in challenges
    ]}

# -------------------- VERIFY --------------------
@app.post("/v1/verify")
def verify(challenge_id: str = Form(...), device_id: str = Form(...), video: UploadFile = File(...), audio: UploadFile = File(None)):
    c.execute("SELECT challenge_type, challenge_value, used FROM challenges WHERE challenge_id=?", (challenge_id,))
    row = c.fetchone()
    if not row:
        return JSONResponse(status_code=400, content={"error": "Invalid challenge"})
    challenge_type, challenge_value, used = row
    if used:
        return JSONResponse(status_code=400, content={"error": "Challenge already used"})
    c.execute("UPDATE challenges SET used=1 WHERE challenge_id=?", (challenge_id,))
    conn.commit()

    video_path = f"uploads/{uuid.uuid4()}_{video.filename}"
    with open(video_path, "wb") as f: f.write(video.file.read())
    audio_path = None
    if audio:
        audio_path = f"uploads/{uuid.uuid4()}_{audio.filename}"
        with open(audio_path, "wb") as f: f.write(audio.file.read())

    result = run_human_verification(video_path, audio_path, challenge_type)

    # Safe clamping
    result["liveness_score"] = min(max(result.get("liveness_score",0),0),1)
    result["lip_sync_score"] = min(max(result.get("lip_sync_score",0),0),1)

    raw_token = f"{device_id}{time.time()}".encode()
    trusted_device_token = hashlib.sha256(raw_token).hexdigest()

    return {
        "verified": result["challenge_passed"],
        "liveness_score": result.get("liveness_score",0),
        "lip_sync_score": result.get("lip_sync_score",0),
        "challenge_passed": result.get("challenge_passed",False),
        "replay_flag": result.get("replay_flag",False),
        "device_trust_score": 0.97,
        "trusted_device_token": trusted_device_token,
        "challenge_type": challenge_type,
        "details":{"reasons":["liveness_ok","challenge_ok"],"timestamp_utc":time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())}
    }

# -------------------- FINALIZE SESSION --------------------
@app.post("/v1/finalize")
async def finalize(request: Request):
    """
    Compute combined session trust score from multiple challenge results.
    """
    data = await request.json()
    results = data.get("results", [])
    device_id = data.get("device_id", "web")

    if not results:
        return JSONResponse(status_code=400, content={"error":"No results provided"})

    # Compute combined trust score (average of challenge liveness_score & lip_sync_score)
    trust_scores = []
    for r in results:
        score = (r.get("liveness_score",0) + r.get("lip_sync_score",0)) / 2
        trust_scores.append(score)

    # Average & scale to 0-100
    avg_score = sum(trust_scores) / len(trust_scores) * 100
    avg_score = min(max(avg_score,0),100)

    # Assign trust level
    if avg_score >= 85:
        trust_level = "high"
    elif avg_score >= 60:
        trust_level = "medium"
    else:
        trust_level = "low"

    return {
        "trust_score": round(avg_score,2),
        "trust_level": trust_level,
        "device_id": device_id,
        "details":{"total_challenges":len(results),"timestamp_utc":time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())}
    }

# -------------------- SERVE FRONTEND --------------------
@app.get("/")
def read_index():
    return FileResponse("index.html")
