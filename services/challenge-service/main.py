"""
Challenge Service
- Nonce generation
- One-time challenge lifecycle
- Challenge validation
- Stateless (uses Redis for state)
"""

from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel
import redis.asyncio as redis
import secrets
import uuid
import json
import time
import os
from typing import List, Optional

# ============================================================================
# CONFIGURATION
# ============================================================================

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")
CHALLENGE_TTL = int(os.getenv("CHALLENGE_TTL", "300"))  # 5 minutes
INTERNAL_AUTH_TOKEN = os.getenv("INTERNAL_AUTH_TOKEN", "secret")

# ============================================================================
# MODELS
# ============================================================================

class ChallengeRequest(BaseModel):
    device_id: str

class Challenge(BaseModel):
    challenge_id: str
    token_id: str
    instruction: str
    difficulty: str
    fast_track: bool

# ============================================================================
# REDIS CONNECTION
# ============================================================================

redis_client = None

async def get_redis():
    global redis_client
    if redis_client is None:
        redis_client = await redis.from_url(REDIS_URL, decode_responses=True)
    return redis_client

# ============================================================================
# FASTAPI APP
# ============================================================================

app = FastAPI(
    title="Certivo Challenge Service",
    description="Challenge generation and validation",
    version="1.0.0"
)

# ============================================================================
# CHALLENGE POOLS
# ============================================================================

CHALLENGE_POOL = {
    "easy": [
        "Turn your head to the left",
        "Turn your head to the right",
        "Blink twice",
    ],
    "medium": [
        "Nod your head up and down",
        "Open your mouth wide",
    ],
    "hard": [
        "Raise your eyebrows",
        "Turn left then right",
    ]
}

# ============================================================================
# HEALTH CHECK
# ============================================================================

@app.get("/health")
async def health_check():
    """Service health check"""
    redis_conn = await get_redis()
    try:
        await redis_conn.ping()
        redis_status = "healthy"
    except Exception as e:
        redis_status = f"unhealthy: {str(e)}"
    
    return {
        "status": "healthy",
        "service": "challenge-service",
        "redis": redis_status,
        "timestamp": time.time()
    }

# ============================================================================
# CHALLENGE GENERATION
# ============================================================================

@app.post("/v1/challenge")
async def create_challenge(
    request: ChallengeRequest,
    x_gateway_token: str = Header(None)
):
    """Generate new challenges for a device"""
    
    # Auth check
    if x_gateway_token != INTERNAL_AUTH_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    redis_conn = await get_redis()
    
    # Check device trust level
    device_key = f"device:{request.device_id}"
    device_data = await redis_conn.get(device_key)
    
    if device_data:
        device_info = json.loads(device_data)
        trust_level = device_info.get("trust_level", "low")
    else:
        trust_level = "low"
    
    # Generate challenges based on trust
    num_challenges = 1 if trust_level == "high" else 2
    difficulty = "easy" if trust_level == "high" else "medium"
    
    challenges = []
    for i in range(num_challenges):
        # Generate unique IDs
        challenge_id = f"ch_{uuid.uuid4().hex[:12]}"
        token_id = f"tok_{secrets.token_urlsafe(16)}"
        
        # Pick random challenge
        import random
        instruction = random.choice(CHALLENGE_POOL[difficulty])
        
        # Store in Redis with TTL
        challenge_data = {
            "challenge_id": challenge_id,
            "token_id": token_id,
            "device_id": request.device_id,
            "instruction": instruction,
            "difficulty": difficulty,
            "created_at": time.time(),
            "used": False
        }
        
        await redis_conn.setex(
            f"challenge:{challenge_id}",
            CHALLENGE_TTL,
            json.dumps(challenge_data)
        )
        
        challenges.append(Challenge(
            challenge_id=challenge_id,
            token_id=token_id,
            instruction=instruction,
            difficulty=difficulty,
            fast_track=(trust_level == "high")
        ))
    
    return {"challenges": challenges}

# ============================================================================
# CHALLENGE VALIDATION
# ============================================================================

@app.get("/v1/challenge/{challenge_id}")
async def get_challenge(
    challenge_id: str,
    x_internal_token: str = Header(None)
):
    """Retrieve challenge details (for verification service)"""
    
    if x_internal_token != INTERNAL_AUTH_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    redis_conn = await get_redis()
    challenge_data = await redis_conn.get(f"challenge:{challenge_id}")
    
    if not challenge_data:
        raise HTTPException(status_code=404, detail="Challenge not found or expired")
    
    challenge = json.loads(challenge_data)
    
    # Check if already used
    if challenge.get("used"):
        raise HTTPException(status_code=400, detail="Challenge already used")
    
    return challenge

# ============================================================================
# MARK CHALLENGE AS USED
# ============================================================================

@app.post("/v1/challenge/{challenge_id}/use")
async def mark_used(
    challenge_id: str,
    x_internal_token: str = Header(None)
):
    """Mark challenge as used (one-time use)"""
    
    if x_internal_token != INTERNAL_AUTH_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    redis_conn = await get_redis()
    challenge_data = await redis_conn.get(f"challenge:{challenge_id}")
    
    if not challenge_data:
        raise HTTPException(status_code=404, detail="Challenge not found")
    
    challenge = json.loads(challenge_data)
    challenge["used"] = True
    challenge["used_at"] = time.time()
    
    # Update in Redis
    await redis_conn.setex(
        f"challenge:{challenge_id}",
        CHALLENGE_TTL,
        json.dumps(challenge)
    )
    
    return {"status": "marked_used"}

# ============================================================================
# STARTUP/SHUTDOWN
# ============================================================================

@app.on_event("startup")
async def startup():
    global redis_client
    redis_client = await redis.from_url(REDIS_URL, decode_responses=True)
    print("✅ Challenge Service started")

@app.on_event("shutdown")
async def shutdown():
    if redis_client:
        await redis_client.close()
    print("🛑 Challenge Service shutdown")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)