"""
Admin Service with Authentication and Authorization
Requires MFA and enforces RBAC
"""

from fastapi import FastAPI, HTTPException, Request, Header, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
import asyncpg
import redis.asyncio as redis
import os
import sys
from typing import Optional, Dict, Any
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'shared'))

from mfa import MFAManager, MFAEnrollment, MFARateLimiter
from rbac import RBACManager, Permission, Role
from admin_sessions import AdminSessionManager
from audit_logger import AuditLogger, AuditAction

# ============================================================================
# CONFIGURATION
# ============================================================================

POSTGRES_URL = os.getenv("POSTGRES_URL", "postgresql://certivo:certivo@postgres:5432/certivo")
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")
SESSION_SECRET = os.getenv("SESSION_SECRET", "CHANGE_ME_IN_PRODUCTION")

# ============================================================================
# MODELS
# ============================================================================

class LoginRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=8, max_length=100)

class MFAVerifyRequest(BaseModel):
    username: str
    token: str = Field(..., regex="^[0-9]{6}$")

class RevokeDeviceRequest(BaseModel):
    device_id: str = Field(..., min_length=8, max_length=64)
    reason: str = Field(..., min_length=5, max_length=500)

class AssignRoleRequest(BaseModel):
    user_id: str = Field(..., min_length=3, max_length=50)
    role: Role

# ============================================================================
# FASTAPI APP
# ============================================================================

app = FastAPI(
    title="Certivo Admin Service",
    version="1.0.0"
)

security = HTTPBearer()

postgres_pool = None
redis_client = None
mfa_manager = None
mfa_enrollment = None
mfa_rate_limiter = None
rbac_manager = None
session_manager = None
audit_logger = None

# ============================================================================
# STARTUP
# ============================================================================

@app.on_event("startup")
async def startup():
    global postgres_pool, redis_client, mfa_manager, mfa_enrollment
    global mfa_rate_limiter, rbac_manager, session_manager, audit_logger
    
    postgres_pool = await asyncpg.create_pool(POSTGRES_URL)
    redis_client = await redis.from_url(REDIS_URL, decode_responses=True)
    
    mfa_manager = MFAManager()
    mfa_enrollment = MFAEnrollment(redis_client)
    mfa_rate_limiter = MFARateLimiter(redis_client)
    rbac_manager = RBACManager(redis_client, postgres_pool)
    session_manager = AdminSessionManager(redis_client, postgres_pool, SESSION_SECRET)
    audit_logger = AuditLogger(postgres_pool)
    
    print("✅ Admin Service started")

@app.on_event("shutdown")
async def shutdown():
    if postgres_pool:
        await postgres_pool.close()
    if redis_client:
        await redis_client.close()

# ============================================================================
# AUTHENTICATION DEPENDENCY
# ============================================================================

async def get_current_admin(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> Dict[str, Any]:
    """
    Dependency: Verify admin session
    
    Returns:
        Admin user data
    
    Raises:
        HTTPException if not authenticated
    """
    
    token = credentials.credentials
    
    # Validate session
    session = await session_manager.validate_session(
        signed_token=token,
        ip_address=request.client.host,
        check_ip_binding=True
    )
    
    if not session:
        await audit_logger.log_action(
            action=AuditAction.UNAUTHORIZED_ACCESS_ATTEMPT,
            actor_id="unknown",
            actor_ip=request.client.host,
            result="failure"
        )
        
        raise HTTPException(
            status_code=401,
            detail={
                "error": "Invalid or expired session",
                "error_code": "INVALID_SESSION"
            }
        )
    
    return session

# ============================================================================
# AUTHORIZATION DEPENDENCY
# ============================================================================

def require_permission(permission: Permission):
    """
    Dependency factory: Require specific permission
    
    Usage:
        @app.get("/endpoint", dependencies=[Depends(require_permission(Permission.VIEW_USERS))])
    """
    
    async def check_permission(
        request: Request,
        admin: Dict[str, Any] = Depends(get_current_admin)
    ):
        user_id = admin["user_id"]
        
        has_permission = await rbac_manager.check_permission(user_id, permission)
        
        if not has_permission:
            await audit_logger.log_action(
                action=AuditAction.PERMISSION_DENIED,
                actor_id=user_id,
                actor_ip=request.client.host,
                details={
                    "required_permission": permission.value,
                    "endpoint": str(request.url)
                },
                result="failure"
            )
            
            raise HTTPException(
                status_code=403,
                detail={
                    "error": "Permission denied",
                    "error_code": "INSUFFICIENT_PERMISSIONS",
                    "required_permission": permission.value
                }
            )
    
    return check_permission

# ============================================================================
# HEALTH CHECK
# ============================================================================

@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "admin"}

# ============================================================================
# AUTHENTICATION ENDPOINTS
# ============================================================================

@app.post("/auth/login")
async def login(request: Request, body: LoginRequest):
    """
    Step 1: Username/password authentication
    
    Returns:
        MFA challenge (requires TOTP verification)
    """
    
    # Validate credentials (simplified - use proper password hashing)
    async with postgres_pool.acquire() as conn:
        user = await conn.fetchrow(
            """
            SELECT user_id, username, password_hash, mfa_secret, mfa_enabled
            FROM admin_users
            WHERE username = $1 AND active = true
            """,
            body.username
        )
    
    if not user:
        await audit_logger.log_action(
            action=AuditAction.LOGIN_FAILURE,
            actor_id=body.username,
            actor_ip=request.client.host,
            details={"reason": "user_not_found"},
            result="failure"
        )
        
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    # Verify password (use bcrypt in production)
    import bcrypt
    if not bcrypt.checkpw(body.password.encode(), user["password_hash"].encode()):
        await audit_logger.log_action(
            action=AuditAction.LOGIN_FAILURE,
            actor_id=body.username,
            actor_ip=request.client.host,
            details={"reason": "invalid_password"},
            result="failure"
        )
        
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    # Check if MFA enabled
    if not user["mfa_enabled"]:
        return {
            "mfa_required": False,
            "message": "MFA not enabled. Please enroll in MFA first."
        }
    
    # Create temporary auth token (pending MFA)
    import secrets
    temp_token = secrets.token_urlsafe(32)
    
    await redis_client.setex(
        f"pending_mfa:{temp_token}",
        300,  # 5 minutes
        user["user_id"]
    )
    
    return {
        "mfa_required": True,
        "temp_token": temp_token,
        "message": "Enter TOTP code from authenticator app"
    }

@app.post("/auth/mfa-verify")
async def verify_mfa(request: Request, body: MFAVerifyRequest):
    """
    Step 2: MFA verification
    
    Returns:
        Session token
    """
    
    # Get user from pending MFA
    temp_token = request.headers.get("X-Temp-Token")
    
    if not temp_token:
        raise HTTPException(status_code=400, detail="Missing temp token")
    
    user_id = await redis_client.get(f"pending_mfa:{temp_token}")
    
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid or expired temp token")
    
    # Get user MFA secret
    async with postgres_pool.acquire() as conn:
        user = await conn.fetchrow(
            "SELECT user_id, username, mfa_secret FROM admin_users WHERE user_id = $1",
            user_id
        )
    
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    
    # Check rate limit
    is_locked, attempts_remaining, lockout_seconds = await mfa_rate_limiter.record_attempt(
        user_id=user_id,
        success=False  # Assume failure initially
    )
    
    if is_locked:
        await audit_logger.log_action(
            action=AuditAction.LOGIN_FAILURE,
            actor_id=user_id,
            actor_ip=request.client.host,
            details={"reason": "mfa_rate_limit"},
            result="failure"
        )
        
        raise HTTPException(
            status_code=429,
            detail=f"Too many failed attempts. Locked out for {lockout_seconds} seconds."
        )
    
    # Verify TOTP
    valid = mfa_manager.verify_totp(user["mfa_secret"], body.token)
    
    if not valid:
        await mfa_rate_limiter.record_attempt(user_id, success=False)
        
        await audit_logger.log_action(
            action=AuditAction.LOGIN_FAILURE,
            actor_id=user_id,
            actor_ip=request.client.host,
            details={"reason": "invalid_mfa_token"},
            result="failure"
        )
        
        raise HTTPException(
            status_code=401,
            detail=f"Invalid MFA token. {attempts_remaining} attempts remaining."
        )
    
    # MFA successful - record success
    await mfa_rate_limiter.record_attempt(user_id, success=True)
    
    # Delete temp token
    await redis_client.delete(f"pending_mfa:{temp_token}")
    
    # Create admin session
    session_token = await session_manager.create_session(
        user_id=user_id,
        ip_address=request.client.host,
        user_agent=request.headers.get("User-Agent", ""),
        mfa_verified=True
    )
    
    await audit_logger.log_action(
        action=AuditAction.LOGIN_SUCCESS,
        actor_id=user_id,
        actor_ip=request.client.host,
        result="success"
    )
    
    return {
        "session_token": session_token,
        "message": "Authentication successful"
    }

@app.post("/auth/logout")
async def logout(
    request: Request,
    admin: Dict[str, Any] = Depends(get_current_admin)
):
    """Logout (revoke session)"""
    
    token = admin["token"]
    user_id = admin["user_id"]
    
    await session_manager.revoke_session(token)
    
    await audit_logger.log_action(
        action=AuditAction.LOGOUT,
        actor_id=user_id,
        actor_ip=request.client.host,
        result="success"
    )
    
    return {"message": "Logged out successfully"}

# ============================================================================
# DEVICE MANAGEMENT (RBAC PROTECTED)
# ============================================================================

@app.post(
    "/device/revoke",
    dependencies=[Depends(require_permission(Permission.REVOKE_DEVICE))]
)
async def revoke_device(
    request: Request,
    body: RevokeDeviceRequest,
    admin: Dict[str, Any] = Depends(get_current_admin)
):
    """
    Revoke device trust
    
    Requires: REVOKE_DEVICE permission
    """
    
    user_id = admin["user_id"]
    
    # Revoke device in database
    async with postgres_pool.acquire() as conn:
        result = await conn.execute(
            """
            UPDATE trusted_devices
            SET trust_revoked = true,
                revoked_at = $1,
                revocation_reason = $2,
                revoked_by = $3
            WHERE device_id = $4
            """,
            datetime.utcnow(),
            body.reason,
            user_id,
            body.device_id
        )
    
    # Audit log
    await audit_logger.log_action(
        action=AuditAction.DEVICE_REVOKED,
        actor_id=user_id,
        actor_ip=request.client.host,
        target_resource=body.device_id,
        details={"reason": body.reason},
        result="success"
    )
    
    return {
        "message": "Device revoked successfully",
        "device_id": body.device_id
    }

# ============================================================================
# USER MANAGEMENT (RBAC PROTECTED)
# ============================================================================

@app.get(
    "/users",
    dependencies=[Depends(require_permission(Permission.VIEW_USERS))]
)
async def list_users(
    admin: Dict[str, Any] = Depends(get_current_admin)
):
    """
    List admin users
    
    Requires: VIEW_USERS permission
    """
    
    async with postgres_pool.acquire() as conn:
        users = await conn.fetch(
            """
            SELECT user_id, username, email, active, mfa_enabled, created_at
            FROM admin_users
            ORDER BY created_at DESC
            """
        )
    
    return {
        "users": [dict(user) for user in users]
    }

@app.post(
    "/users/{user_id}/role",
    dependencies=[Depends(require_permission(Permission.MANAGE_ROLES))]
)
async def assign_role(
    request: Request,
    user_id: str,
    body: AssignRoleRequest,
    admin: Dict[str, Any] = Depends(get_current_admin)
):
    """
    Assign role to user
    
    Requires: MANAGE_ROLES permission (Super Admin only)
    """
    
    actor_id = admin["user_id"]
    
    # Assign role
    await rbac_manager.assign_role_to_user(
        user_id=user_id,
        role=body.role,
        assigned_by=actor_id
    )
    
    # Audit log
    await audit_logger.log_action(
        action=AuditAction.ROLE_ASSIGNED,
        actor_id=actor_id,
        actor_ip=request.client.host,
        target_resource=user_id,
        details={"role": body.role.value},
        result="success"
    )
    
    return {
        "message": "Role assigned successfully",
        "user_id": user_id,
        "role": body.role.value
    }

# ============================================================================
# AUDIT LOGS (RBAC PROTECTED)
# ============================================================================

@app.get(
    "/audit-logs",
    dependencies=[Depends(require_permission(Permission.VIEW_AUDIT_LOGS))]
)
async def get_audit_logs(
    actor_id: Optional[str] = None,
    action: Optional[str] = None,
    limit: int = 100,
    admin: Dict[str, Any] = Depends(get_current_admin)
):
    """
    Query audit logs
    
    Requires: VIEW_AUDIT_LOGS permission
    """
    
    action_enum = AuditAction(action) if action else None
    
    logs = await audit_logger.query_logs(
        actor_id=actor_id,
        action=action_enum,
        limit=limit
    )
    
    return {
        "logs": logs,
        "total": len(logs)
    }

@app.get(
    "/audit-logs/verify",
    dependencies=[Depends(require_permission(Permission.VIEW_AUDIT_LOGS))]
)
async def verify_audit_integrity(
    start_id: Optional[int] = None,
    end_id: Optional[int] = None,
    admin: Dict[str, Any] = Depends(get_current_admin)
):
    """
    Verify audit log integrity
    
    Requires: VIEW_AUDIT_LOGS permission
    """
    
    result = await audit_logger.verify_integrity(
        start_id=start_id,
        end_id=end_id
    )
    
    return result

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8005)