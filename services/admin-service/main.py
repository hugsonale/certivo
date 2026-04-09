"""
Admin Service
- Isolated behind strong authz
- Network controls
- Admin dashboard
- Device management
"""

from fastapi import FastAPI, Depends, HTTPException, Header, Request
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
import asyncpg
import redis.asyncio as redis
import secrets
import os
import time
from typing import Optional
from datetime import datetime, timedelta

# ============================================================================
# CONFIGURATION
# ============================================================================

POSTGRES_URL = os.getenv("POSTGRES_URL", "postgresql://certivo:certivo@postgres:5432/certivo")
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "changeme123")
INTERNAL_AUTH_TOKEN = os.getenv("INTERNAL_AUTH_TOKEN", "secret")

# ============================================================================
# DATABASE
# ============================================================================

postgres_pool = None
redis_client = None

async def get_postgres():
    global postgres_pool
    if postgres_pool is None:
        postgres_pool = await asyncpg.create_pool(POSTGRES_URL, min_size=2, max_size=10)
    return postgres_pool

async def get_redis():
    global redis_client
    if redis_client is None:
        redis_client = await redis.from_url(REDIS_URL, decode_responses=True)
    return redis_client

# ============================================================================
# AUTHENTICATION
# ============================================================================

security = HTTPBasic()

def verify_admin(credentials: HTTPBasicCredentials = Depends(security)):
    """Verify admin credentials"""
    correct_username = secrets.compare_digest(credentials.username, ADMIN_USERNAME)
    correct_password = secrets.compare_digest(credentials.password, ADMIN_PASSWORD)
    
    if not (correct_username and correct_password):
        raise HTTPException(
            status_code=401,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username

# ============================================================================
# NETWORK ACCESS CONTROL
# ============================================================================

ALLOWED_ADMIN_IPS = os.getenv("ALLOWED_ADMIN_IPS", "127.0.0.1,::1").split(",")

async def verify_network_access(request: Request):
    """Verify request comes from allowed network"""
    client_ip = request.client.host
    
    if client_ip not in ALLOWED_ADMIN_IPS and "*" not in ALLOWED_ADMIN_IPS:
        raise HTTPException(
            status_code=403,
            detail=f"Access denied from IP: {client_ip}"
        )
    return True

# ============================================================================
# FASTAPI APP
# ============================================================================

app = FastAPI(
    title="Certivo Admin Service",
    description="Administrative interface with strong authz",
    version="1.0.0",
    dependencies=[Depends(verify_network_access)]
)

# ============================================================================
# HEALTH CHECK
# ============================================================================

@app.get("/health")
async def health_check():
    """Admin service health check"""
    return {
        "status": "healthy",
        "service": "admin-service",
        "timestamp": time.time()
    }

# ============================================================================
# DASHBOARD
# ============================================================================

@app.get("/admin/dashboard", response_class=HTMLResponse)
async def dashboard(admin: str = Depends(verify_admin)):
    """Admin dashboard"""
    return """
    <html>
        <head><title>Certivo Admin</title></head>
        <body>
            <h1>Certivo Admin Dashboard</h1>
            <p>Authenticated as: {admin}</p>
            <ul>
                <li><a href="/admin/stats">System Statistics</a></li>
                <li><a href="/admin/devices">Device Management</a></li>
                <li><a href="/admin/sessions">Recent Sessions</a></li>
            </ul>
        </body>
    </html>
    """.replace("{admin}", admin)

# ============================================================================
# SYSTEM STATS
# ============================================================================

@app.get("/admin/stats")
async def get_stats(admin: str = Depends(verify_admin)):
    """Get system statistics"""
    pg_pool = await get_postgres()
    
    async with pg_pool.acquire() as conn:
        # Total sessions
        total_sessions = await conn.fetchval("SELECT COUNT(*) FROM sessions")
        
        # Success rate
        high_trust = await conn.fetchval(
            "SELECT COUNT(*) FROM sessions WHERE trust_level = 'high'"
        )
        
        # Recent activity
        recent_24h = await conn.fetchval(
            """
            SELECT COUNT(*) FROM sessions 
            WHERE timestamp_utc >= $1
            """,
            datetime.utcnow() - timedelta(hours=24)
        )
        
        # Device stats
        total_devices = await conn.fetchval("SELECT COUNT(*) FROM trusted_devices")
        trusted_devices = await conn.fetchval(
            "SELECT COUNT(*) FROM trusted_devices WHERE trust_level = 'high'"
        )
    
    return {
        "total_sessions": total_sessions,
        "high_trust_sessions": high_trust,
        "success_rate": round((high_trust / total_sessions * 100), 2) if total_sessions > 0 else 0,
        "recent_24h": recent_24h,
        "total_devices": total_devices,
        "trusted_devices": trusted_devices
    }

# ============================================================================
# DEVICE MANAGEMENT
# ============================================================================

@app.get("/admin/devices")
async def list_devices(
    admin: str = Depends(verify_admin),
    limit: int = 50,
    offset: int = 0
):
    """List all devices"""
    pg_pool = await get_postgres()
    
    async with pg_pool.acquire() as conn:
        devices = await conn.fetch(
            """
            SELECT device_id, trust_level, total_verifications, 
                   successful_verifications, last_verified_utc
            FROM trusted_devices
            ORDER BY last_verified_utc DESC
            LIMIT $1 OFFSET $2
            """,
            limit, offset
        )
    
    return {
        "devices": [dict(d) for d in devices],
        "total": len(devices)
    }

@app.post("/admin/device/{device_id}/revoke")
async def revoke_device_trust(
    device_id: str,
    admin: str = Depends(verify_admin)
):
    """Revoke trust from a device"""
    pg_pool = await get_postgres()
    redis_conn = await get_redis()
    
    async with pg_pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE trusted_devices 
            SET trust_level = 'low', trust_revoked = true, revoked_at = $1
            WHERE device_id = $2
            """,
            datetime.utcnow(),
            device_id
        )
    
    # Clear from cache
    await redis_conn.delete(f"device:{device_id}")
    
    return {"status": "revoked", "device_id": device_id}

# ============================================================================
# SESSION LOGS
# ============================================================================

@app.get("/admin/sessions")
async def recent_sessions(
    admin: str = Depends(verify_admin),
    limit: int = 50
):
    """Get recent verification sessions"""
    pg_pool = await get_postgres()
    
    async with pg_pool.acquire() as conn:
        sessions = await conn.fetch(
            """
            SELECT session_id, device_id, trust_score, trust_level,
                   total_challenges, failed_challenges, timestamp_utc
            FROM sessions
            ORDER BY timestamp_utc DESC
            LIMIT $1
            """,
            limit
        )
    
    return {
        "sessions": [dict(s) for s in sessions]
    }

# ============================================================================
# STARTUP/SHUTDOWN
# ============================================================================

@app.on_event("startup")
async def startup():
    global postgres_pool, redis_client
    postgres_pool = await asyncpg.create_pool(POSTGRES_URL, min_size=2, max_size=10)
    redis_client = await redis.from_url(REDIS_URL, decode_responses=True)
    print("✅ Admin Service started")
    print(f"⚠️  ALLOWED IPs: {ALLOWED_ADMIN_IPS}")

@app.on_event("shutdown")
async def shutdown():
    if postgres_pool:
        await postgres_pool.close()
    if redis_client:
        await redis_client.close()
    print("🛑 Admin Service shutdown")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8005)