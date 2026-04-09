"""
Risk Scoring Service
- Fusion of liveness, behavior, device, reputation
- ML-based risk analysis
- Trust level calculation
- Device fingerprinting
"""

from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel
import redis.asyncio as redis
import httpx
import json
import time
import os
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
import asyncpg

# ============================================================================
# CONFIGURATION
# ============================================================================

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")
POSTGRES_URL = os.getenv("POSTGRES_URL", "postgresql://certivo:certivo@postgres:5432/certivo")
INTERNAL_AUTH_TOKEN = os.getenv("INTERNAL_AUTH_TOKEN", "secret")

# ============================================================================
# MODELS
# ============================================================================

class ChallengeResult(BaseModel):
    challenge_passed: bool
    liveness_score: float
    confidence: float
    challenge_id: str

class FinalizeRequest(BaseModel):
    device_id: str
    results: List[Dict[str, Any]]
    session_metadata: Optional[Dict[str, Any]] = None

# ============================================================================
# DATABASE & REDIS
# ============================================================================

redis_client = None
postgres_pool = None

async def get_redis():
    global redis_client
    if redis_client is None:
        redis_client = await redis.from_url(REDIS_URL, decode_responses=True)
    return redis_client

async def get_postgres():
    global postgres_pool
    if postgres_pool is None:
        postgres_pool = await asyncpg.create_pool(
            POSTGRES_URL,
            min_size=5,
            max_size=20,
            command_timeout=60
        )
    return postgres_pool

# ============================================================================
# FASTAPI APP
# ============================================================================

app = FastAPI(
    title="Certivo Risk Scoring Service",
    description="ML-based risk analysis and trust scoring",
    version="1.0.0"
)

# ============================================================================
# HEALTH CHECK
# ============================================================================

@app.get("/health")
async def health_check():
    """Service health check"""
    redis_conn = await get_redis()
    pg_pool = await get_postgres()
    
    # Check Redis
    try:
        await redis_conn.ping()
        redis_status = "healthy"
    except Exception as e:
        redis_status = f"unhealthy: {str(e)}"
    
    # Check Postgres
    try:
        async with pg_pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        postgres_status = "healthy"
    except Exception as e:
        postgres_status = f"unhealthy: {str(e)}"
    
    return {
        "status": "healthy",
        "service": "risk-scoring",
        "redis": redis_status,
        "postgres": postgres_status,
        "timestamp": time.time()
    }

# ============================================================================
# RISK SCORING ALGORITHM
# ============================================================================

async def calculate_risk_score(
    device_id: str,
    results: List[Dict[str, Any]],
    session_metadata: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Multi-factor risk scoring:
    1. Liveness scores (40%)
    2. Challenge success rate (30%)
    3. Device reputation (20%)
    4. Behavioral patterns (10%)
    """
    
    redis_conn = await get_redis()
    pg_pool = await get_postgres()
    
    # ================================================================
    # FACTOR 1: Liveness Score Analysis (40%)
    # ================================================================
    
    liveness_scores = [r.get("liveness_score", 0) for r in results]
    avg_liveness = sum(liveness_scores) / len(liveness_scores) if liveness_scores else 0
    
    # Variance check (bots have suspiciously consistent scores)
    if len(liveness_scores) > 1:
        variance = sum((x - avg_liveness) ** 2 for x in liveness_scores) / len(liveness_scores)
        # Low variance is suspicious (perfect scores every time)
        variance_penalty = 0 if variance > 0.01 else -10
    else:
        variance_penalty = 0
    
    liveness_factor = (avg_liveness * 40) + variance_penalty
    
    # ================================================================
    # FACTOR 2: Challenge Success Rate (30%)
    # ================================================================
    
    total_challenges = len(results)
    passed_challenges = sum(1 for r in results if r.get("challenge_passed", False))
    success_rate = (passed_challenges / total_challenges) if total_challenges > 0 else 0
    
    challenge_factor = success_rate * 30
    
    # ================================================================
    # FACTOR 3: Device Reputation (20%)
    # ================================================================
    
    # Get device history from Postgres
    async with pg_pool.acquire() as conn:
        device_history = await conn.fetch(
            """
            SELECT 
                COUNT(*) as total_verifications,
                SUM(CASE WHEN trust_level = 'high' THEN 1 ELSE 0 END) as high_trust_count,
                MAX(last_verified_utc) as last_verified
            FROM trusted_devices
            WHERE device_id = $1
            """,
            device_id
        )
        
        if device_history and device_history[0]['total_verifications'] > 0:
            hist = device_history[0]
            reputation_score = (hist['high_trust_count'] / hist['total_verifications']) * 20
            
            # Bonus for established devices
            if hist['total_verifications'] > 5:
                reputation_score += 5
        else:
            # New device - neutral score
            reputation_score = 10
    
    # Check if flagged as suspicious
    suspicious_flag = await redis_conn.get(f"suspicious:{device_id}")
    if suspicious_flag:
        reputation_score -= 15
    
    # ================================================================
    # FACTOR 4: Behavioral Patterns (10%)
    # ================================================================
    
    # Check timing patterns (bots complete challenges too quickly)
    behavior_score = 10  # Default
    
    # Check for suspicious metadata
    if session_metadata:
        # Too fast completion
        if session_metadata.get("total_time_seconds", 999) < 5:
            behavior_score -= 5
        
        # Missing browser features
        if not session_metadata.get("has_webgl", True):
            behavior_score -= 2
        
        # Headless browser detection
        if session_metadata.get("is_headless", False):
            behavior_score -= 8
    
    # ================================================================
    # FINAL SCORE CALCULATION
    # ================================================================
    
    total_score = max(0, min(100, 
        liveness_factor + challenge_factor + reputation_score + behavior_score
    ))
    
    # Determine trust level
    if total_score >= 80:
        trust_level = "high"
    elif total_score >= 50:
        trust_level = "medium"
    else:
        trust_level = "low"
    
    return {
        "trust_score": round(total_score, 2),
        "trust_level": trust_level,
        "breakdown": {
            "liveness_factor": round(liveness_factor, 2),
            "challenge_factor": round(challenge_factor, 2),
            "reputation_score": round(reputation_score, 2),
            "behavior_score": round(behavior_score, 2)
        },
        "flags": {
            "low_variance": variance_penalty < 0,
            "suspicious_device": suspicious_flag is not None,
            "new_device": device_history[0]['total_verifications'] == 0 if device_history else True
        }
    }

# ============================================================================
# FINALIZE SESSION
# ============================================================================

@app.post("/v1/finalize")
async def finalize_session(
    request: FinalizeRequest,
    x_gateway_token: str = Header(None)
):
    """Calculate final risk score and trust level"""
    
    # Auth check
    if x_gateway_token != INTERNAL_AUTH_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    # Calculate risk score
    risk_analysis = await calculate_risk_score(
        device_id=request.device_id,
        results=request.results,
        session_metadata=request.session_metadata or {}
    )
    
    # Store in database
    pg_pool = await get_postgres()
    session_id = f"session_{request.device_id}_{int(time.time())}"
    
    async with pg_pool.acquire() as conn:
        # Store session
        await conn.execute(
            """
            INSERT INTO sessions 
            (session_id, device_id, trust_score, trust_level, total_challenges, failed_challenges, timestamp_utc)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            """,
            session_id,
            request.device_id,
            risk_analysis['trust_score'],
            risk_analysis['trust_level'],
            len(request.results),
            sum(1 for r in request.results if not r.get("challenge_passed", False)),
            datetime.utcnow()
        )
        
        # Update device trust
        await conn.execute(
            """
            INSERT INTO trusted_devices 
            (device_id, trust_level, total_verifications, successful_verifications, last_verified_utc)
            VALUES ($1, $2, 1, $3, $4)
            ON CONFLICT (device_id) 
            DO UPDATE SET
                trust_level = $2,
                total_verifications = trusted_devices.total_verifications + 1,
                successful_verifications = trusted_devices.successful_verifications + $3,
                last_verified_utc = $4
            """,
            request.device_id,
            risk_analysis['trust_level'],
            1 if risk_analysis['trust_level'] in ['high', 'medium'] else 0,
            datetime.utcnow()
        )
    
    # Cache in Redis for fast access
    redis_conn = await get_redis()
    await redis_conn.setex(
        f"device:{request.device_id}",
        86400,  # 24 hours
        json.dumps({
            "trust_level": risk_analysis['trust_level'],
            "trust_score": risk_analysis['trust_score'],
            "last_update": time.time()
        })
    )
    
    return {
        "session_id": session_id,
        **risk_analysis
    }

# ============================================================================
# DEVICE REPUTATION QUERY
# ============================================================================

@app.get("/v1/device/{device_id}/reputation")
async def get_device_reputation(
    device_id: str,
    x_internal_token: str = Header(None)
):
    """Get device reputation for other services"""
    
    if x_internal_token != INTERNAL_AUTH_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    # Check Redis cache first
    redis_conn = await get_redis()
    cached = await redis_conn.get(f"device:{device_id}")
    
    if cached:
        return json.loads(cached)
    
    # Query from database
    pg_pool = await get_postgres()
    async with pg_pool.acquire() as conn:
        device = await conn.fetchrow(
            """
            SELECT trust_level, total_verifications, successful_verifications
            FROM trusted_devices
            WHERE device_id = $1
            """,
            device_id
        )
        
        if device:
            return {
                "trust_level": device['trust_level'],
                "total_verifications": device['total_verifications'],
                "success_rate": device['successful_verifications'] / device['total_verifications']
            }
        else:
            return {
                "trust_level": "unknown",
                "total_verifications": 0,
                "success_rate": 0
            }

# ============================================================================
# STARTUP/SHUTDOWN
# ============================================================================

@app.on_event("startup")
async def startup():
    global redis_client, postgres_pool
    redis_client = await redis.from_url(REDIS_URL, decode_responses=True)
    postgres_pool = await asyncpg.create_pool(POSTGRES_URL, min_size=5, max_size=20)
    print("✅ Risk Scoring Service started")

@app.on_event("shutdown")
async def shutdown():
    if redis_client:
        await redis_client.close()
    if postgres_pool:
        await postgres_pool.close()
    print("🛑 Risk Scoring Service shutdown")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8003)