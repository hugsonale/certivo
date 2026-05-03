"""
Admin Session Management
Secure session handling with rotation and revocation
"""

import secrets
import hmac
import hashlib
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
import redis.asyncio as redis
import asyncpg
import json


class AdminSessionManager:
    """
    Manage admin sessions with security features
    
    Features:
    - Cryptographically secure session tokens
    - Session rotation on privilege escalation
    - Concurrent session limits
    - Automatic expiry and refresh
    - Session revocation
    - Device binding
    """
    
    def __init__(
        self,
        redis_client: redis.Redis,
        postgres_pool: asyncpg.Pool,
        session_secret: str
    ):
        self.redis = redis_client
        self.postgres = postgres_pool
        self.session_secret = session_secret
        
        # Session configuration
        self.session_ttl = 3600  # 1 hour
        self.refresh_threshold = 300  # Refresh if < 5 minutes remaining
        self.max_sessions_per_user = 3  # Max concurrent sessions
        self.require_mfa = True
    
    def generate_session_token(self) -> str:
        """
        Generate cryptographically secure session token
        
        Returns:
            URL-safe token (43 characters)
        """
        return secrets.token_urlsafe(32)
    
    def sign_session_token(self, token: str, user_id: str) -> str:
        """
        Sign session token with HMAC
        
        Returns:
            Signed token: token.signature
        """
        
        message = f"{token}:{user_id}".encode()
        signature = hmac.new(
            self.session_secret.encode(),
            message,
            hashlib.sha256
        ).hexdigest()[:16]  # 16 chars
        
        return f"{token}.{signature}"
    
    def verify_session_token_signature(
        self,
        signed_token: str,
        user_id: str
    ) -> Optional[str]:
        """
        Verify session token signature
        
        Returns:
            Unsigned token if valid, None otherwise
        """
        
        try:
            token, signature = signed_token.rsplit(".", 1)
        except ValueError:
            return None
        
        # Re-sign and compare
        expected_signed = self.sign_session_token(token, user_id)
        expected_signature = expected_signed.rsplit(".", 1)[1]
        
        # Constant-time comparison
        if not secrets.compare_digest(signature, expected_signature):
            return None
        
        return token
    
    async def create_session(
        self,
        user_id: str,
        ip_address: str,
        user_agent: str,
        mfa_verified: bool = False,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Optional[str]:
        """
        Create new admin session
        
        Args:
            user_id: Admin user ID
            ip_address: Client IP
            user_agent: User agent string
            mfa_verified: Whether MFA was completed
            metadata: Additional session metadata
        
        Returns:
            Signed session token if successful
        """
        
        if self.require_mfa and not mfa_verified:
            return None
        
        # Check concurrent session limit
        active_sessions = await self.get_active_sessions(user_id)
        
        if len(active_sessions) >= self.max_sessions_per_user:
            # Revoke oldest session
            oldest = min(active_sessions, key=lambda s: s["created_at"])
            await self.revoke_session(oldest["token"])
        
        # Generate session token
        session_token = self.generate_session_token()
        signed_token = self.sign_session_token(session_token, user_id)
        
        # Create session data
        session_data = {
            "user_id": user_id,
            "token": session_token,
            "ip_address": self._hash_ip(ip_address),
            "user_agent_hash": self._hash_string(user_agent),
            "mfa_verified": str(mfa_verified),
            "created_at": datetime.utcnow().isoformat(),
            "last_activity": datetime.utcnow().isoformat(),
            "expires_at": (datetime.utcnow() + timedelta(seconds=self.session_ttl)).isoformat(),
            "metadata": json.dumps(metadata or {})
        }
        
        # Store in Redis
        session_key = f"admin_session:{session_token}"
        await self.redis.hset(session_key, mapping=session_data)
        await self.redis.expire(session_key, self.session_ttl)
        
        # Add to user's active sessions set
        await self.redis.sadd(f"user_sessions:{user_id}", session_token)
        await self.redis.expire(f"user_sessions:{user_id}", self.session_ttl)
        
        # Store in Postgres for audit trail
        async with self.postgres.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO admin_sessions
                (session_token, user_id, ip_address_hash, user_agent_hash,
                 mfa_verified, created_at, expires_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                """,
                session_token,
                user_id,
                session_data["ip_address"],
                session_data["user_agent_hash"],
                mfa_verified,
                datetime.utcnow(),
                datetime.utcnow() + timedelta(seconds=self.session_ttl)
            )
        
        return signed_token
    
    async def validate_session(
        self,
        signed_token: str,
        ip_address: Optional[str] = None,
        check_ip_binding: bool = True
    ) -> Optional[Dict[str, Any]]:
        """
        Validate session token
        
        Args:
            signed_token: Signed session token
            ip_address: Current IP address (for binding check)
            check_ip_binding: Whether to enforce IP binding
        
        Returns:
            Session data if valid, None otherwise
        """
        
        # Get session data from Redis
        session_data = await self.redis.hgetall(f"admin_session:{signed_token}")
        
        if not session_data:
            return None
        
        user_id = session_data.get("user_id")
        
        # Verify signature
        token = self.verify_session_token_signature(signed_token, user_id)
        if not token:
            return None
        
        # Check expiry
        expires_at = datetime.fromisoformat(session_data["expires_at"])
        if datetime.utcnow() > expires_at:
            await self.revoke_session(token)
            return None
        
        # Check IP binding (optional but recommended)
        if check_ip_binding and ip_address:
            stored_ip_hash = session_data.get("ip_address")
            current_ip_hash = self._hash_ip(ip_address)
            
            if stored_ip_hash != current_ip_hash:
                # IP changed - potential session hijacking
                await self.revoke_session(token)
                return None
        
        # Update last activity
        await self.redis.hset(
            f"admin_session:{token}",
            "last_activity",
            datetime.utcnow().isoformat()
        )
        
        # Check if needs refresh
        time_remaining = (expires_at - datetime.utcnow()).total_seconds()
        
        if time_remaining < self.refresh_threshold:
            # Extend session
            new_expiry = datetime.utcnow() + timedelta(seconds=self.session_ttl)
            await self.redis.hset(
                f"admin_session:{token}",
                "expires_at",
                new_expiry.isoformat()
            )
            await self.redis.expire(f"admin_session:{token}", self.session_ttl)
        
        return dict(session_data)
    
    async def rotate_session(
        self,
        old_signed_token: str,
        reason: str = "privilege_escalation"
    ) -> Optional[str]:
        """
        Rotate session token (on privilege escalation)
        
        Args:
            old_signed_token: Current session token
            reason: Reason for rotation
        
        Returns:
            New signed session token
        """
        
        # Validate old session
        old_session = await self.validate_session(old_signed_token, check_ip_binding=False)
        
        if not old_session:
            return None
        
        user_id = old_session["user_id"]
        
        # Generate new token
        new_token = self.generate_session_token()
        new_signed_token = self.sign_session_token(new_token, user_id)
        
        # Copy session data with new token
        new_session_data = {**old_session, "token": new_token}
        new_session_data["created_at"] = datetime.utcnow().isoformat()
        new_session_data["rotation_reason"] = reason
        
        # Store new session
        await self.redis.hset(
            f"admin_session:{new_token}",
            mapping=new_session_data
        )
        await self.redis.expire(f"admin_session:{new_token}", self.session_ttl)
        
        # Update user's sessions set
        await self.redis.sadd(f"user_sessions:{user_id}", new_token)
        
        # Revoke old session
        await self.revoke_session(old_session["token"])
        
        return new_signed_token
    
    async def revoke_session(self, session_token: str) -> bool:
        """
        Revoke session
        
        Args:
            session_token: Session token to revoke
        
        Returns:
            True if revoked
        """
        
        # Get session data
        session_data = await self.redis.hgetall(f"admin_session:{session_token}")
        
        if not session_data:
            return False
        
        user_id = session_data.get("user_id")
        
        # Delete from Redis
        await self.redis.delete(f"admin_session:{session_token}")
        
        # Remove from user's active sessions
        await self.redis.srem(f"user_sessions:{user_id}", session_token)
        
        # Mark as revoked in Postgres
        async with self.postgres.acquire() as conn:
            await conn.execute(
                """
                UPDATE admin_sessions
                SET revoked = true, revoked_at = $1
                WHERE session_token = $2
                """,
                datetime.utcnow(),
                session_token
            )
        
        return True
    
    async def revoke_all_user_sessions(self, user_id: str) -> int:
        """
        Revoke all sessions for a user
        
        Returns:
            Number of sessions revoked
        """
        
        active_sessions = await self.get_active_sessions(user_id)
        
        for session in active_sessions:
            await self.revoke_session(session["token"])
        
        return len(active_sessions)
    
    async def get_active_sessions(self, user_id: str) -> List[Dict[str, Any]]:
        """Get all active sessions for user"""
        
        session_tokens = await self.redis.smembers(f"user_sessions:{user_id}")
        
        sessions = []
        
        for token in session_tokens:
            session_data = await self.redis.hgetall(f"admin_session:{token}")
            if session_data:
                sessions.append(dict(session_data))
        
        return sessions
    
    def _hash_ip(self, ip: str) -> str:
        """Hash IP address for privacy"""
        return hashlib.sha256(ip.encode()).hexdigest()[:16]
    
    def _hash_string(self, value: str) -> str:
        """Hash string for privacy"""
        return hashlib.sha256(value.encode()).hexdigest()[:16]