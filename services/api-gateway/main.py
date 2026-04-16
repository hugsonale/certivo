"""
API Gateway with integrated error codes and idempotency
"""

from fastapi import FastAPI, HTTPException, Header, Request
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
import httpx
import redis.asyncio as redis
import os
import sys

# Add shared modules to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'shared'))

from error_codes import (
    ErrorCode, APIError, ValidationError, ForbiddenError, 
    RateLimitError as CustomRateLimitError, InternalError
)
from idempotency import IdempotencyManager
from middleware import error_handler_middleware

# Configuration
VERIFICATION_SERVICE_URL = os.getenv("VERIFICATION_SERVICE_URL", "http://verification-api:8001")
CHALLENGE_SERVICE_URL = os.getenv("CHALLENGE_SERVICE_URL", "http://challenge-service:8002")
RISK_SCORING_URL = os.getenv("RISK_SCORING_URL", "http://risk-scoring:8003")
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")
INTERNAL_AUTH_TOKEN = os.getenv("INTERNAL_AUTH_TOKEN", "secret")

# Rate limiter
limiter = Limiter(key_func=get_remote_address)

# FastAPI app
app = FastAPI(
    title="Certivo API Gateway",
    version="1.0.0",
    description="Production API Gateway with error codes and idempotency"
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Global state
redis_client = None
idempotency_manager = None

@app.on_event("startup")
async def startup():
    global redis_client, idempotency_manager
    redis_client = await redis.from_url(REDIS_URL, decode_responses=True)
    idempotency_manager = IdempotencyManager(redis_client)
    print("✅ API Gateway started with error codes & idempotency")

@app.on_event("shutdown")
async def shutdown():
    if redis_client:
        await redis_client.close()

# Add error handler middleware
@app.middleware("http")
async def error_middleware(request: Request, call_next):
    return await error_handler_middleware(request, call_next)

@app.get("/health")
async def health():
    return {"status": "healthy", "service": "api-gateway"}

@app.post("/v1/challenge")
@limiter.limit("10/minute")
async def create_challenge(
    request: Request,
    idempotency_key: str = Header(None, alias="Idempotency-Key")
):
    """Generate verification challenge with idempotency support"""
    
    # Check idempotency
    if idempotency_key:
        cached = await idempotency_manager.get_cached_response(
            idempotency_key, "/v1/challenge"
        )
        if cached:
            return JSONResponse(
                content=cached["response"],
                headers={"X-Idempotent-Replay": "true"}
            )
    
    # Get request body
    body = await request.json()
    
    # Validate device_id
    if not body.get("device_id"):
        raise ValidationError(
            ErrorCode.MISSING_REQUIRED_FIELD,
            "device_id is required",
            field="device_id"
        )
    
    # Forward to challenge service
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                f"{CHALLENGE_SERVICE_URL}/generate",
                json=body,
                headers={"X-Internal-Token": INTERNAL_AUTH_TOKEN},
                timeout=10.0
            )
            
            if response.status_code != 200:
                raise InternalError("Challenge service unavailable")
            
            result = response.json()
            
            # Cache if idempotency key provided
            if idempotency_key:
                await idempotency_manager.cache_response(
                    idempotency_key, "/v1/challenge", result, 200
                )
            
            return result
            
        except httpx.TimeoutException:
            raise InternalError("Request timeout")
        except httpx.RequestError:
            raise InternalError("Challenge service unavailable")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)