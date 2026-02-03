from fastapi import FastAPI, Query, Request, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
import uuid
from challenge_engine import generate_adaptive_challenges
from typing import List
from fastapi.responses import FileResponse
import os
app = FastAPI()
from human_verification import run_human_verification
import tempfile


# Allow frontend to call API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"]
)

# In-memory store for trusted devices
trusted_devices = {}  # device_id -> bool

# In-memory store for session results (for demo)
session_results_store = {}  # device_id -> List of results

@app.get("/v1/challenge")
async def get_challenge(request: Request, device_id: str = Query(...)):
    """
    Returns 3 adaptive challenges with unique token_id for verification.
    Trusted devices get Fast-Track mode.
    """
    user_agent = request.headers.get("user-agent", "unknown")
    is_trusted = trusted_devices.get(device_id, False)

    # Generate challenges
    challenges = generate_adaptive_challenges(prev_results=[], num=3, trusted=is_trusted)

    # Normalize challenges with token_id
    normalized = [
        {
            "challenge_id": ch.get("challenge_id"),
            "token_id": str(uuid.uuid4()),
            "instruction": ch.get("challenge_value"),
            "difficulty": ch.get("difficulty", "medium"),
            "fast_track": is_trusted
        }
        for ch in challenges
    ]

    return {"trusted_device": is_trusted, "challenges": normalized}

@app.post("/v1/verify")
async def verify_challenge(
    device_id: str = Form(...),
    challenge_id: str = Form(...),
    token_id: str = Form(...),
    video: UploadFile = File(...)
):
    """
    Receives video submission and runs real human verification.
    """

    # 1. Save uploaded video to a temp file
    with tempfile.NamedTemporaryFile(delete=False, suffix=".webm") as tmp:
        video_bytes = await video.read()
        tmp.write(video_bytes)
        video_path = tmp.name

    # 2. Run human verification logic
    session_id = device_id  # V1 simplification
    result = run_human_verification(
        session_id=session_id,
        challenge_id=challenge_id,
        video_path=video_path
    )

    # 3. Cleanup temp file
    try:
        os.remove(video_path)
    except:
        pass

    # 4. Store result for session
    session_results_store.setdefault(device_id, []).append({
        "challenge_id": challenge_id,
        "token_id": token_id,
        "challenge_passed": result.get("challenge_passed", False),
        "liveness_score": result.get("liveness_score", 0.0)
    })

    return result


@app.post("/v1/finalize")
async def finalize_verification(request: Request):
    """
    Calculates final trust score based on all challenges for the device.
    """
    data = await request.json()
    results = data.get("results", [])
    device_id = data.get("device_id", "unknown")

    if not results:
        return {"trust_score": 0, "trust_level": "low"}

    # Simple scoring: pass=100, fail=0, average all
    score = int(sum(100 if r.get("challenge_passed") else 0 for r in results) / len(results))

    if score >= 80:
        level = "high"
    elif score >= 50:
        level = "medium"
    else:
        level = "low"

    # Mark device as trusted if high
    if level == "high":
        trusted_devices[device_id] = True

    return {"trust_score": score, "trust_level": level}

# Serve index.html at root
@app.get("/")
def read_index():
    html_path = "index.html"  # make sure index.html is in the same folder as main.py
    if os.path.exists(html_path):
        return FileResponse(html_path)
    return {"detail": "index.html not found"}