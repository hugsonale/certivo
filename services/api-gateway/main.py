"""
API Gateway with Multi-Dimensional Rate Limiting
- IP, Subnet, ASN, Device, Session, Challenge tracking
- Distributed enforcement via Redis
- Progressive penalties
"""

from fastapi import FastAPI, Request, HTTPException, Header, Response
from fastapi.responses import JSONResponse
import httpx
import redis.asyncio as redis
import os
import sys
import time
import hashlib
from typing import Dict, Any, Optional

# Add shared modules to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'shared'))

from error_codes import ErrorCode, RateLimitError, InternalError
from rate_limiter import (
    DistributedRateLimiter, RateLimitDimension, PenaltyLevel
)
from asn_lookup import asn_lookup

# ============================================================================
# CONFIGURATION
# ============================================================================

VERIFICATION_SERVICE_URL = os.getenv("VERIFICATION_SERVICE_URL", "http://verification-api:8001")
CHALLENGE_SERVICE_URL = os.getenv("CHALLENGE_SERVICE_URL", "http://challenge-service:8002")
RISK_SCORING_URL = os.getenv("RISK_SCORING_URL", "http://risk-scoring:8003")
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")
INTERNAL_AUTH_TOKEN = os.getenv("INTERNAL_AUTH_TOKEN", "secret")

# ============================================================================
# FASTAPI APP
# ============================================================================

app = FastAPI(
    title="Certivo API Gateway",
    description="Multi-dimensional rate limiting with progressive penalties",
    version="1.0.0"
)

redis_client = None
rate_limiter = None

# ============================================================================
# METRICS TRACKING
# ============================================================================

async def track_bypass_attempt(
    dimension: str,
    identifier: str,
    previous_identifier: Optional[str] = None
):
    """
    Track bypass attempts (e.g., IP rotation)
    Increases attacker cost metric
    """
    metric_key = f"bypass_attempts:{dimension}"
    
    # Increment bypass counter
    await redis_client.incr(metric_key)
    
    # Store details
    detail_key = f"bypass_detail:{dimension}:{identifier}"
    await redis_client.setex(
        detail_key,
        3600,  # 1 hour
        f"previous:{previous_identifier},timestamp:{int(time.time())}"
    )
    
    # Log for monitoring
    print(f"⚠️  Bypass attempt detected: {dimension} - {identifier}")

async def get_bypass_metrics() -> Dict[str, int]:
    """Get bypass attempt metrics"""
    dimensions = ["ip", "subnet", "asn", "device"]
    metrics = {}
    
    for dimension in dimensions:
        key = f"bypass_attempts:{dimension}"
        count = await redis_client.get(key)
        metrics[dimension] = int(count) if count else 0
    
    return metrics

# ============================================================================
# STARTUP/SHUTDOWN
# ============================================================================

@app.on_event("startup")
async def startup():
    global redis_client, rate_limiter
    redis_client = await redis.from_url(REDIS_URL, decode_responses=True)
    rate_limiter = DistributedRateLimiter(redis_client)
    print("✅ API Gateway started with multi-dimensional rate limiting")

@app.on_event("shutdown")
async def shutdown():
    if redis_client:
        await redis_client.close()

# ============================================================================
# MIDDLEWARE: MULTI-DIMENSIONAL RATE LIMITING
# ============================================================================

@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    """
    Multi-dimensional rate limiting middleware
    Checks: IP, Subnet, ASN, Device
    """
    
    # Skip health check
    if request.url.path == "/health":
        return await call_next(request)
    
    # Extract identifiers
    client_ip = request.client.host
    device_id = request.headers.get("X-Device-ID")
    
    # Build dimensions to check
    dimensions = {
        RateLimitDimension.IP: client_ip
    }
    
    # Add subnet
    subnet = rate_limiter._get_subnet(client_ip, prefix_length=24)
    dimensions[RateLimitDimension.SUBNET] = subnet
    
    # Add ASN (async lookup)
    asn = await asn_lookup.get_asn(client_ip)
    if asn:
        dimensions[RateLimitDimension.ASN] = asn
    
    # Add device if provided
    if device_id:
        dimensions[RateLimitDimension.DEVICE] = device_id
    
    # Check all dimensions
    result = await rate_limiter.check_multi_dimensional(dimensions)
    
    # Handle blocked requests
    if not result["allowed"]:
        # Track bypass attempt if IP changed but device same
        if device_id:
            previous_ip_key = f"device_ip:{device_id}"
            previous_ip = await redis_client.get(previous_ip_key)
            
            if previous_ip and previous_ip != client_ip:
                await track_bypass_attempt("ip_rotation", client_ip, previous_ip)
        
        # Return 429 with details
        raise RateLimitError(
            message=result.get("reason", "Rate limit exceeded"),
            retry_after=result["retry_after"],
            dimension=result.get("dimension"),
            limit=result.get("limit"),
            window="60 seconds"
        )
    
    # Handle soft throttle (add delay)
    if result["penalty_level"] == PenaltyLevel.SOFT_THROTTLE:
        # Add artificial delay (0.5 - 2 seconds based on proximity to limit)
        throttle_ratio = result["current_count"] / result["limit"]
        delay = 0.5 + (throttle_ratio * 1.5)
        
        import asyncio
        await asyncio.sleep(delay)
        
        response = await call_next(request)
        response.headers["X-RateLimit-Throttled"] = "true"
        return response
    
    # Store device-IP mapping for bypass detection
    if device_id:
        device_ip_key = f"device_ip:{device_id}"
        await redis_client.setex(device_ip_key, 3600, client_ip)
    
    # Add rate limit headers
    response = await call_next(request)
    
    response.headers["X-RateLimit-Limit"] = str(result.get("limit", "N/A"))
    response.headers["X-RateLimit-Remaining"] = str(
        result.get("limit", 0) - result.get("current_count", 0)
    )
    response.headers["X-RateLimit-Reset"] = str(
        int(time.time()) + result.get("reset_in", 0)
    )
    
    return response

# ============================================================================
# HEALTH CHECK
# ============================================================================

@app.get("/health")
async def health():
    """Gateway health check"""
    try:
        await redis_client.ping()
        redis_status = "healthy"
    except Exception as e:
        redis_status = f"unhealthy: {str(e)}"
    
    return {
        "status": "healthy",
        "service": "api-gateway",
        "redis": redis_status,
        "timestamp": time.time()
    }

# ============================================================================
# METRICS ENDPOINT
# ============================================================================

@app.get("/metrics/bypass-attempts")
async def get_bypass_attempt_metrics():
    """Get bypass attempt metrics (for monitoring)"""
    metrics = await get_bypass_metrics()
    
    return {
        "bypass_attempts": metrics,
        "timestamp": time.time()
    }

# ============================================================================
# CHALLENGE ENDPOINT
# ============================================================================

@app.post("/v1/challenge")
async def create_challenge(
    request: Request,
    x_device_id: str = Header(None, alias="X-Device-ID")
):
    """Generate challenge with session-level rate limiting"""
    
    # Additional session-level rate limit
    if x_device_id:
        session_result = await rate_limiter.check_rate_limit(
            RateLimitDimension.SESSION,
            x_device_id
        )
        
        if not session_result["allowed"]:
            raise RateLimitError(
                message="Too many challenge requests for this session",
                retry_after=session_result["retry_after"],
                dimension="session",
                limit=session_result["limit"],
                window="5 minutes"
            )
    
    # Get request body
    body = await request.json()
    
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
            
            return response.json()
            
        except httpx.TimeoutException:
            raise InternalError("Request timeout")
        except httpx.RequestError:
            raise InternalError("Challenge service unavailable")

# ============================================================================
# VERIFY ENDPOINT
# ============================================================================

@app.post("/v1/verify")
async def verify_challenge(
    request: Request
):
    """Verify challenge with challenge-level rate limiting"""
    
    # Parse form data
    form = await request.form()
    challenge_id = form.get("challenge_id")
    
    # Challenge-level rate limit
    if challenge_id:
        challenge_result = await rate_limiter.check_rate_limit(
            RateLimitDimension.CHALLENGE,
            challenge_id
        )
        
        if not challenge_result["allowed"]:
            raise RateLimitError(
                message="Too many verification attempts for this challenge",
                retry_after=challenge_result["retry_after"],
                dimension="challenge",
                limit=challenge_result["limit"],
                window="5 minutes"
            )
    
    # Forward to verification service
    async with httpx.AsyncClient() as client:
        try:
            # Reconstruct multipart form
            files = {}
            data = {}
            
            for key, value in form.items():
                if hasattr(value, 'read'):  # File
                    content = await value.read()
                    files[key] = (value.filename, content, value.content_type)
                else:
                    data[key] = value
            
            response = await client.post(
                f"{VERIFICATION_SERVICE_URL}/v1/verify",
                files=files,
                data=data,
                headers={"X-Gateway-Token": INTERNAL_AUTH_TOKEN},
                timeout=30.0
            )
            
            return Response(
                content=response.content,
                status_code=response.status_code,
                headers=dict(response.headers)
            )
            
        except httpx.TimeoutException:
            raise InternalError("Verification timeout")
        except httpx.RequestError:
            raise InternalError("Verification service unavailable")

# ============================================================================
# FINALIZE ENDPOINT
# ============================================================================

@app.post("/v1/finalize")
async def finalize_session(request: Request):
    """Finalize verification session"""
    
    body = await request.json()
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                f"{RISK_SCORING_URL}/v1/finalize",
                json=body,
                headers={"X-Gateway-Token": INTERNAL_AUTH_TOKEN},
                timeout=10.0
            )
            
            if response.status_code != 200:
                raise InternalError("Risk scoring service unavailable")
            
            return response.json()
            
        except httpx.TimeoutException:
            raise InternalError("Request timeout")
        except httpx.RequestError:
            raise InternalError("Risk scoring service unavailable")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)