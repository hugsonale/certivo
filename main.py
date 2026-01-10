from fastapi import FastAPI, UploadFile, File, Form, Body, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
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

# -------------------- IN-MEMORY STORES --------------------
in_memory_sessions = []           # Stores session results
trusted_devices = {}              # {device_id: trusted_token}
submitted_video_hashes = set()    # For replay protection
challenge_timestamps = {}         # {challenge_id: timestamp_utc}

# -------------------- GET CHALLENGES --------------------
@app.get("/v1/challenge")
async def get_challenge(request: Request, device_id: str = Query(...)):
    is_trusted = device_id in trusted_devices
    challenge_count = 1 if is_trusted else 3

    challenges = generate_challenges(num=challenge_count)

    now = time.time()
    for ch in challenges:
        challenge_timestamps[ch["challenge_id"]] = now

    return {
        "trusted_device": is_trusted,
        "challenges": [
            {
                "challenge_id": ch["challenge_id"],
                "challenge_type": ch["challenge_type"],
                "instruction": ch["challenge_value"],
                "expires_in": 30 if is_trusted else 60
            }
            for ch in challenges
        ]
    }

# -------------------- VERIFY CHALLENGE WITH REPLAY PROTECTION --------------------
@app.post("/v1/verify")
async def verify(
    challenge_id: str = Form(...),
    device_id: str = Form(...),
    video: UploadFile = File(...),
    audio: UploadFile = File(None)
):
    """
    Phase 3.3:
    - Replay protection via video hash
    - Only returns biometric signals
    - Verifies challenge expiry
    """

    # Check if challenge exists
    challenge_time = challenge_timestamps.get(challenge_id)
    if not challenge_time:
        return {"error": "Invalid or expired challenge.", "replay_flag": True}

    if time.time() - challenge_time > 90:  # 90s expiry buffer
        return {"error": "Challenge expired.", "replay_flag": True}

    # Read video bytes & hash for replay protection
    video_bytes = await video.read()
    video_hash = hashlib.sha256(video_bytes).hexdigest()

    if video_hash in submitted_video_hashes:
        return {"error": "Replay detected. Video already submitted.", "replay_flag": True}

    # Save video
    video_path = f"uploads/{uuid.uuid4()}_{video.filename}"
    with open(video_path, "wb") as f:
        f.write(video_bytes)
    submitted_video_hashes.add(video_hash)

    # Save audio if present
    audio_path = None
    if audio:
        audio_bytes = await audio.read()
        audio_path = f"uploads/{uuid.uuid4()}_{audio.filename}"
        with open(audio_path, "wb") as f:
            f.write(audio_bytes)

    # Run biometric verification
    result = run_human_verification(video_path, audio_path, "generic")

    return {
        "liveness_score": result.get("liveness_score", 0),
        "lip_sync_score": result.get("lip_sync_score", 0),
        "reaction_time": result.get("reaction_time", 1.0),
        "facial_stability": result.get("facial_stability", 1.0),
        "blink_count": result.get("blink_count", 0),
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

    for r in results:
        # Phase 3.2/3.3: challenge pass sanity check
        instruction = r.get("instruction_type")
        blink_count = r.get("blink_count", 0)

        if instruction == "blink" and blink_count < 2:
            r["challenge_passed"] = False

        # Score calculation
        liveness = max(0, min(1, r.get("liveness_score", 0)))
        lip_sync = max(0, min(1, r.get("lip_sync_score", 0)))
        reaction_time = max(0, min(1, r.get("reaction_time", 1)))
        stability = max(0, min(1, r.get("facial_stability", 1)))

        blink_penalty = min(max(blink_count - 5, 0) * 0.02, 0.2)

        trust_scores.append(
            liveness * 0.35 +
            lip_sync * 0.25 +
            reaction_time * 0.15 +
            stability * 0.15 -
            blink_penalty
        )

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

    if trust_score >= 85:
        level = "high"
    elif trust_score >= 60:
        level = "medium"
    else:
        level = "low"

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

    # Mark device trusted if score >=85
    if trust_score >= 85:
        trusted_devices[device_id] = hashlib.sha256(
            f"{device_id}:{user_agent}".encode()
        ).hexdigest()

    return session_record

# -------------------- ANALYTICS --------------------
@app.get("/v1/sessions")
async def get_sessions(device_id: str = Query(None)):
    if device_id:
        return {"sessions": [s for s in in_memory_sessions if s["device_id"] == device_id]}
    return {"sessions": in_memory_sessions}

# -------------------- SERVE FRONTEND --------------------
@app.get("/")
def read_index():
    return FileResponse("index.html")
