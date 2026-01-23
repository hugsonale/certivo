from fastapi import FastAPI, UploadFile, File, Form, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import uuid
import shutil
import os
from fastapi.responses import FileResponse


app = FastAPI(title="Certivo Prime Verification API")

# ---------------- CORS ----------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, restrict to frontend domain
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------- In-memory storage ----------------
CHALLENGES_DB = [
    {"challenge_id": "ch_1", "instruction": "Smile widely", "token_id": str(uuid.uuid4())},
    {"challenge_id": "ch_2", "instruction": "Raise eyebrows", "token_id": str(uuid.uuid4())},
    {"challenge_id": "ch_3", "instruction": "Blink twice", "token_id": str(uuid.uuid4())}
]

TRUSTED_DEVICES = set()  # store trusted device IDs

SESSIONS = {}  # device_id -> session results

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# ---------------- Endpoints ----------------

@app.get("/v1/challenge")
async def get_challenges(device_id: str = Query(...)):
    """
    Load challenges for the device.
    Returns the challenges + whether device is trusted.
    """
    trusted_device = device_id in TRUSTED_DEVICES
    challenges = [{"challenge_id": ch["challenge_id"], "instruction": ch["instruction"], "token_id": ch["token_id"]} for ch in CHALLENGES_DB]
    return {"challenges": challenges, "trusted_device": trusted_device}


@app.post("/v1/verify")
async def verify_challenge(
    video: UploadFile = File(...),
    challenge_id: str = Form(...),
    device_id: str = Form(...),
):
    """
    Verify the uploaded video for a challenge.
    Simulated liveness & success logic.
    """
    # Save video temporarily
    tmp_path = os.path.join(UPLOAD_DIR, f"{uuid.uuid4()}.webm")
    with open(tmp_path, "wb") as f:
        shutil.copyfileobj(video.file, f)

    # --------- Simulate verification logic ---------
    # Here you could integrate ML models for lip sync/liveness
    result = {
        "challenge_passed": True,  # assume pass
        "liveness_score": 0.95,
        "lip_sync_score": 0.9
    }

    # Update session results
    if device_id not in SESSIONS:
        SESSIONS[device_id] = []
    SESSIONS[device_id].append(result)

    return JSONResponse(result)


@app.post("/v1/finalize")
async def finalize_session(
    device_id: str = Form(...),
):
    """
    Calculate overall trust score based on session results.
    """
    results = SESSIONS.get(device_id, [])
    if not results:
        return JSONResponse({"trust_score": 0, "trust_level": "low"})

    # Simple scoring logic
    score = sum(r.get("liveness_score",0)*100 for r in results) / len(results)
    if score >= 80: level = "high"
    elif score >= 50: level = "medium"
    else: level = "low"

    # Mark device as trusted if score is high
    if level == "high":
        TRUSTED_DEVICES.add(device_id)

    return JSONResponse({"trust_score": round(score,1), "trust_level": level})


# ---------------- Test / Admin ----------------
@app.get("/v1/reset")
async def reset_sessions():
    """
    Reset all sessions & trusted devices (for testing purposes).
    """
    SESSIONS.clear()
    TRUSTED_DEVICES.clear()
    # Clear uploads
    for f in os.listdir(UPLOAD_DIR):
        os.remove(os.path.join(UPLOAD_DIR, f))
    return {"status":"reset done"}

@app.get("/")
async def serve_index():
    return FileResponse("index.html")