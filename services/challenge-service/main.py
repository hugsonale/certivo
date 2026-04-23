"""
Challenge Service with PASETO tokens and session binding
"""

from fastapi import FastAPI, HTTPException, Header, Request
from pydantic import BaseModel
import redis.asyncio as redis
import os
import time
import sys
from typing import Optional, Dict, Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'shared'))

from error_codes import ErrorCode, ValidationError
from paseto_tokens import PasetoTokenManager
from session_binding import SessionMetadataExtractor
from challenge_entropy import ChallengeGenerator

# ============================================================================
# CONFIGURATION
# ============================================================================

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")
CHALLENGE_TTL = int(os.getenv("CHALLENGE_TTL", "300"))
INTERNAL_AUTH_TOKEN = os.getenv("INTERNAL_AUTH_TOKEN", "secret")

# ============================================================================
# MODELS
# ============================================================================

class ChallengeRequest(BaseModel):
    device_id: str
    trust_level: Optional[str] = "unknown"
    client_metadata: Optional[Dict[str, Any]] = None

# ============================================================================
# FASTAPI APP
# ============================================================================

app = FastAPI(
    title="Certivo Challenge Service - PASETO",
    version="3.0.0"
)

redis_client = None
paseto_manager = None
challenge_generator = None

# ============================================================================
# STARTUP
# ============================================================================

@app.on_event("startup")
async def startup():
    global redis_client, paseto_manager, challenge_generator
    
    redis_client = await redis.from_url(REDIS_URL, decode_responses=True)
    paseto_manager = PasetoTokenManager()
    challenge_generator = ChallengeGenerator()
    
    print("✅ Challenge Service started with PASETO tokens")

@app.on_event("shutdown")
async def shutdown():
    if redis_client:
        await redis_client.close()

# ============================================================================
# HEALTH CHECK
# ============================================================================

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "challenge-service-paseto",
        "timestamp": time.time()
    }

# ============================================================================
# CHALLENGE GENERATION WITH PASETO
# ============================================================================

@app.post("/generate")
async def generate_challenge(
    request_body: ChallengeRequest,
    request: Request,
    x_internal_token: str = Header(None)
):
    """Generate challenge with PASETO token and session binding"""
    
    # Auth check
    if x_internal_token != INTERNAL_AUTH_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    # Extract server-side session metadata
    server_metadata = SessionMetadataExtractor.extract_from_request(request)
    
    # Merge with client-provided metadata
    client_metadata = request_body.client_metadata or {}
    client_meta_processed = SessionMetadataExtractor.extract_from_client_data(client_metadata)
    
    full_metadata = SessionMetadataExtractor.merge_metadata(
        server_metadata,
        client_meta_processed
    )
    
    # Generate challenges
    session_challenges = challenge_generator.generate_session_challenges(
        device_id=request_body.device_id,
        trust_level=request_body.trust_level or "unknown",
        target_entropy_bits=20.0
    )
    
    api_challenges = []
    
    for challenge_data in session_challenges:
        challenge_id = challenge_data["challenge_id"]
        
        # Generate cryptographic nonce
        import secrets
        nonce = secrets.token_urlsafe(32)
        
        # Create PASETO token with session binding
        paseto_token = paseto_manager.create_challenge_token(
            challenge_id=challenge_id,
            device_id=request_body.device_id,
            nonce=nonce,
            session_metadata=full_metadata,
            ttl_seconds=CHALLENGE_TTL
        )
        
        # Store challenge in Redis
        challenge_key = f"challenge:{challenge_id}"
        metadata = {
            "challenge_id": challenge_id,
            "device_id": request_body.device_id,
            "nonce": nonce,
            "consumed": "false",
            "session_metadata": str(full_metadata),
            "created_at": time.time()
        }
        
        await redis_client.hset(challenge_key, mapping=metadata)
        await redis_client.expire(challenge_key, CHALLENGE_TTL)
        
        api_challenges.append({
            "challenge_id": challenge_id,
            "token_id": paseto_token,
            "instruction": challenge_data["instruction"],
            "steps": challenge_data["steps"],
            "expires_at": challenge_data["timestamp"],
            "entropy_bits": challenge_data["entropy_bits"]
        })
    
    return {
        "challenges": api_challenges,
        "session_entropy_bits": challenge_generator.calculate_session_entropy(session_challenges)
    }

# ============================================================================
# TOKEN VALIDATION WITH PASETO
# ============================================================================

@app.post("/validate-token")
async def validate_token(
    token_id: str,
    challenge_id: str,
    device_id: str,
    current_session_metadata: Dict[str, Any],
    x_internal_token: str = Header(None)
):
    """Validate PASETO token with session binding check"""
    
    if x_internal_token != INTERNAL_AUTH_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    # Decode and verify PASETO token
    payload = paseto_manager.verify_and_decode_token(
        token=token_id,
        expected_device_id=device_id,
        expected_session_metadata=current_session_metadata
    )
    
    if not payload:
        raise HTTPException(status_code=403, detail="Invalid or tampered token")
    
    # Verify challenge exists
    challenge_key = f"challenge:{challenge_id}"
    challenge_data = await redis_client.hgetall(challenge_key)
    
    if not challenge_data:
        raise HTTPException(status_code=404, detail="Challenge not found")
    
    # Verify not consumed
    if challenge_data.get('consumed') == 'true':
        raise HTTPException(status_code=403, detail="Token already consumed")
    
    return {
        "valid": True,
        "nonce": payload["nonce"],
        "watermark_seed": payload.get("watermark_seed")
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)