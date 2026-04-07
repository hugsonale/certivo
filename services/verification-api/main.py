"""
Verification API Service - Stateless
- Video processing
- Liveness detection
- Challenge validation
- Horizontally scalable
"""

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Header
from fastapi.responses import JSONResponse
import os
import uuid
import httpx
from typing import Optional
import time

# ============================================================================
# CONFIGURATION
# ============================================================================

CHALLENGE_SERVICE_URL = os.getenv("CHALLENGE_SERVICE_URL", "http://challenge-service:8002")
RISK_SCORING_URL = os.getenv("RISK_SCORING_URL", "http://risk-scoring:8003")
ASYNC_WORKER_URL = os.getenv("ASYNC_WORKER_URL", "http://async-worker:8004")
S3_BUCKET = os.getenv("S3_BUCKET", "certivo-videos")
INTERNAL_AUTH_TOKEN = os.getenv("INTERNAL_AUTH_TOKEN", "secret")

# ============================================================================
# FASTAPI APP
# ============================================================================

app = FastAPI(
    title="Certivo Verification API",
    description="Stateless verification service",
    version="1.0.0"
)

# ============================================================================
# AUTHENTICATION
# ============================================================================

def verify_internal_token(x_gateway_token: str = Header(None)):
    """Verify requests come from API Gateway"""
    if x_gateway_token != INTERNAL_AUTH_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return True

# ============================================================================
# HEALTH CHECK
# ============================================================================

@app.get("/health")
async def health_check():
    """Service health check"""
    return {
        "status": "healthy",
        "service": "verification-api",
        "version": "1.0.0",
        "timestamp": time.time()
    }

# ============================================================================
# VERIFICATION ENDPOINT
# ============================================================================

@app.post("/v1/verify")
async def verify(
    video: UploadFile = File(...),
    challenge_id: str = Form(...),
    token_id: str = Form(...),
    device_id: str = Form(...),
    authenticated: bool = Header(default=False, alias="x-gateway-token")
):
    """
    Verify challenge submission
    - Stateless processing
    - Offload to async worker
    - Return immediate response
    """
    
    # Generate unique session ID
    session_id = str(uuid.uuid4())
    
    # Save video to object storage (async)
    video_key = f"{device_id}/{session_id}/{video.filename}"
    video_content = await video.read()
    
    # Offload to async worker for processing
    async with httpx.AsyncClient() as client:
        try:
            # Send to async worker
            response = await client.post(
                f"{ASYNC_WORKER_URL}/process",
                json={
                    "session_id": session_id,
                    "challenge_id": challenge_id,
                    "token_id": token_id,
                    "device_id": device_id,
                    "video_key": video_key,
                    "video_size": len(video_content)
                },
                files={"video": (video.filename, video_content, video.content_type)},
                timeout=30.0,
                headers={"X-Internal-Token": INTERNAL_AUTH_TOKEN}
            )
            
            result = response.json()
            
            return JSONResponse(content={
                "session_id": session_id,
                "challenge_passed": result.get("challenge_passed", False),
                "confidence": result.get("confidence", 0),
                "error": result.get("error"),
                "timestamp": time.time()
            })
            
        except httpx.RequestError as e:
            raise HTTPException(status_code=503, detail="Worker service unavailable")


# ============================================================================
# STARTUP
# ============================================================================

@app.on_event("startup")
async def startup():
    """Initialize service"""
    print("✅ Verification API started")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)