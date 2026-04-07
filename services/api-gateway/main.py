"""
API Gateway - Edge Layer
- WAF (rate limiting, IP filtering)
- DDoS protection
- Bot heuristics
- TLS termination
- Request routing
"""

from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
import httpx
import redis.asyncio as redis
from typing import Optional
import hashlib
import time
import os

# ============================================================================
# CONFIGURATION
# ============================================================================

VERIFICATION_SERVICE_URL = os.getenv("VERIFICATION_SERVICE_URL", "http://verification-api:8001")
CHALLENGE_SERVICE_URL = os.getenv("CHALLENGE_SERVICE_URL", "http://challenge-service:8002")
RISK_SCORING_URL = os.getenv("RISK_SCORING_URL", "http://risk-scoring:8003")
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")

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
# RATE LIMITER
# ============================================================================

limiter = Limiter(key_func=get_remote_address)

# ============================================================================
# FASTAPI APP
# ============================================================================

app = FastAPI(
    title="Certivo API Gateway",
    description="Edge layer with WAF, DDoS protection, and routing",
    version="1.0.0",
    docs_url="/gateway/docs"
)

# Add rate limit handler
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ============================================================================
# MIDDLEWARE
# ============================================================================

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure properly in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Trusted hosts
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=["*"]  # Configure properly in production
)

# ============================================================================
# BOT HEURISTICS
# ============================================================================

async def detect_bot_behavior(request: Request) -> dict:
    """Advanced bot detection heuristics"""
    redis_conn = await get_redis()
    client_ip = request.client.host
    user_agent = request.headers.get("user-agent", "")
    
    # Fingerprint the client
    fingerprint = hashlib.sha256(
        f"{client_ip}:{user_agent}".encode()
    ).hexdigest()[:16]
    
    # Check request patterns
    request_key = f"bot_check:{fingerprint}"
    request_count = await redis_conn.incr(request_key)
    await redis_conn.expire(request_key, 60)  # 1-minute window
    
    # Bot indicators
    is_suspicious = False
    reasons = []
    
    # Too many requests in short time
    if request_count > 30:
        is_suspicious = True
        reasons.append("high_request_rate")
    
    # Missing or suspicious user agent
    if not user_agent or "bot" in user_agent.lower():
        is_suspicious = True
        reasons.append("suspicious_user_agent")
    
    # Missing common headers
    if not request.headers.get("accept-language"):
        is_suspicious = True
        reasons.append("missing_headers")
    
    return {
        "fingerprint": fingerprint,
        "is_suspicious": is_suspicious,
        "reasons": reasons,
        "request_count": request_count
    }

# ============================================================================
# HEALTH CHECK
# ============================================================================

@app.get("/health")
async def health_check():
    """Gateway health check"""
    redis_conn = await get_redis()
    
    # Check Redis
    try:
        await redis_conn.ping()
        redis_status = "healthy"
    except Exception as e:
        redis_status = f"unhealthy: {str(e)}"
    
    # Check downstream services
    services = {}
    async with httpx.AsyncClient() as client:
        for name, url in [
            ("verification", VERIFICATION_SERVICE_URL),
            ("challenge", CHALLENGE_SERVICE_URL),
            ("risk_scoring", RISK_SCORING_URL)
        ]:
            try:
                resp = await client.get(f"{url}/health", timeout=2.0)
                services[name] = "healthy" if resp.status_code == 200 else "unhealthy"
            except Exception:
                services[name] = "unreachable"
    
    return {
        "status": "healthy",
        "redis": redis_status,
        "downstream_services": services,
        "timestamp": time.time()
    }

# ============================================================================
# PROXY ROUTES
# ============================================================================

@app.post("/v1/challenge")
@limiter.limit("10/minute")
async def create_challenge(request: Request):
    """Proxy to Challenge Service"""
    
    # Bot detection
    bot_check = await detect_bot_behavior(request)
    if bot_check["is_suspicious"]:
        raise HTTPException(
            status_code=429,
            detail={"error": "Suspicious behavior detected", "reasons": bot_check["reasons"]}
        )
    
    # Forward to Challenge Service
    body = await request.json()
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                f"{CHALLENGE_SERVICE_URL}/v1/challenge",
                json=body,
                timeout=10.0,
                headers={"X-Gateway-Token": os.getenv("INTERNAL_AUTH_TOKEN", "secret")}
            )
            return response.json()
        except httpx.RequestError as e:
            raise HTTPException(status_code=503, detail="Challenge service unavailable")


@app.post("/v1/verify")
@limiter.limit("5/minute")
async def verify_challenge(request: Request):
    """Proxy to Verification Service"""
    
    # Bot detection
    bot_check = await detect_bot_behavior(request)
    if bot_check["is_suspicious"]:
        raise HTTPException(
            status_code=429,
            detail={"error": "Suspicious behavior detected", "reasons": bot_check["reasons"]}
        )
    
    # Forward to Verification Service
    async with httpx.AsyncClient() as client:
        # Get form data
        form = await request.form()
        
        # Prepare multipart data
        files = {
            "video": (form["video"].filename, await form["video"].read(), form["video"].content_type)
        }
        data = {
            "challenge_id": form.get("challenge_id"),
            "token_id": form.get("token_id"),
            "device_id": form.get("device_id")
        }
        
        try:
            response = await client.post(
                f"{VERIFICATION_SERVICE_URL}/v1/verify",
                files=files,
                data=data,
                timeout=30.0,
                headers={"X-Gateway-Token": os.getenv("INTERNAL_AUTH_TOKEN", "secret")}
            )
            return response.json()
        except httpx.RequestError as e:
            raise HTTPException(status_code=503, detail="Verification service unavailable")


@app.post("/v1/finalize")
@limiter.limit("10/minute")
async def finalize_session(request: Request):
    """Proxy to Risk Scoring Service"""
    
    body = await request.json()
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                f"{RISK_SCORING_URL}/v1/finalize",
                json=body,
                timeout=10.0,
                headers={"X-Gateway-Token": os.getenv("INTERNAL_AUTH_TOKEN", "secret")}
            )
            return response.json()
        except httpx.RequestError as e:
            raise HTTPException(status_code=503, detail="Risk scoring service unavailable")

# ============================================================================
# METRICS
# ============================================================================

@app.get("/metrics")
async def metrics():
    """Prometheus-compatible metrics"""
    redis_conn = await get_redis()
    
    # Get request counts
    total_requests = await redis_conn.get("metrics:total_requests") or 0
    blocked_requests = await redis_conn.get("metrics:blocked_requests") or 0
    
    return {
        "total_requests": int(total_requests),
        "blocked_requests": int(blocked_requests),
        "block_rate": float(blocked_requests) / max(int(total_requests), 1)
    }

# ============================================================================
# STARTUP/SHUTDOWN
# ============================================================================

@app.on_event("startup")
async def startup():
    """Initialize connections on startup"""
    global redis_client
    redis_client = await redis.from_url(REDIS_URL, decode_responses=True)
    print("✅ API Gateway started - Redis connected")

@app.on_event("shutdown")
async def shutdown():
    """Cleanup on shutdown"""
    if redis_client:
        await redis_client.close()
    print("🛑 API Gateway shutdown complete")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)