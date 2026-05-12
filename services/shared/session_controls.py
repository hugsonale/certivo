"""
Timing and Session Controls
Strict TTL enforcement and attempt rate limiting
"""

from typing import Dict, Any, Optional, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass
from enum import Enum
import asyncpg
import redis.asyncio as redis
import secrets
import logging

logger = logging.getLogger(__name__)


class SessionStatus(str, Enum):
    """Session lifecycle status"""
    ACTIVE = "active"
    COMPLETED = "completed"
    EXPIRED = "expired"
    REVOKED = "revoked"
    RATE_LIMITED = "rate_limited"


@dataclass
class SessionConfig:
    """Session configuration parameters"""
    
    # Challenge TTL
    challenge_ttl_seconds: int = 300  # 5 minutes
    
    # Session TTL
    session_ttl_seconds: int = 600  # 10 minutes
    
    # Attempt limits
    max_attempts_per_session: int = 3
    max_attempts_per_device_hourly: int = 10
    max_attempts_per_device_daily: int = 50
    max_attempts_per_ip_hourly: int = 20
    max_attempts_per_ip_daily: int = 100
    
    # Retry delays (progressive backoff)
    retry_delay_after_fail_seconds: int = 10  # After 1st failure
    retry_delay_multiplier: float = 2.0  # Exponential backoff
    max_retry_delay_seconds: int = 300  # Max 5 minutes
    
    # Rate limit windows
    rate_limit_window_seconds: int = 3600  # 1 hour
    rate_limit_lockout_seconds: int = 3600  # 1 hour lockout
    
    # Time authority
    allow_client_time: bool = False  # Server time only


class SessionController:
    """
    Session and timing control manager
    
    Features:
    - Strict TTL enforcement (challenge and session)
    - Attempt rate limiting (per session, device, IP)
    - Progressive retry delays
    - Server time as sole authority
    - Brute force prevention
    """
    
    def __init__(
        self,
        postgres_pool: asyncpg.Pool,
        redis_client: redis.Redis,
        config: Optional[SessionConfig] = None
    ):
        self.postgres = postgres_pool
        self.redis = redis_client
        self.config = config or SessionConfig()
    
    async def create_session(
        self,
        device_id: str,
        ip_address: str,
        challenge_id: str
    ) -> Dict[str, Any]:
        """
        Create new verification session
        
        Args:
            device_id: Device identifier
            ip_address: Client IP address
            challenge_id: Challenge identifier
        
        Returns:
            Session data with expiry
        """
        
        # Check if device/IP is rate limited
        is_limited, reason = await self._check_rate_limits(device_id, ip_address)
        
        if is_limited:
            logger.warning(f"Rate limited: {device_id} - {reason}")
            raise RateLimitException(reason)
        
        # Generate session ID
        session_id = self._generate_session_id()
        
        # Server time as authority
        created_at = datetime.utcnow()
        challenge_expires_at = created_at + timedelta(
            seconds=self.config.challenge_ttl_seconds
        )
        session_expires_at = created_at + timedelta(
            seconds=self.config.session_ttl_seconds
        )
        
        # Store session
        session_data = {
            "session_id": session_id,
            "device_id": device_id,
            "ip_address": ip_address,
            "challenge_id": challenge_id,
            "status": SessionStatus.ACTIVE.value,
            "attempts": 0,
            "max_attempts": self.config.max_attempts_per_session,
            "created_at": created_at.isoformat(),
            "challenge_expires_at": challenge_expires_at.isoformat(),
            "session_expires_at": session_expires_at.isoformat(),
            "last_attempt_at": None,
            "next_retry_allowed_at": None
        }
        
        # Store in Redis (fast lookup)
        await self.redis.hset(
            f"session:{session_id}",
            mapping={k: str(v) for k, v in session_data.items()}
        )
        await self.redis.expireat(
            f"session:{session_id}",
            int(session_expires_at.timestamp())
        )
        
        # Store in Postgres (persistent record)
        async with self.postgres.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO verification_sessions
                (session_id, device_id, ip_address, challenge_id, status,
                 attempts, max_attempts, created_at, challenge_expires_at,
                 session_expires_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                """,
                session_id,
                device_id,
                ip_address,
                challenge_id,
                SessionStatus.ACTIVE.value,
                0,
                self.config.max_attempts_per_session,
                created_at,
                challenge_expires_at,
                session_expires_at
            )
        
        logger.info(
            f"✅ Session created: {session_id}\n"
            f"   Challenge TTL: {self.config.challenge_ttl_seconds}s\n"
            f"   Session TTL: {self.config.session_ttl_seconds}s\n"
            f"   Max attempts: {self.config.max_attempts_per_session}"
        )
        
        return session_data
    
    async def validate_session(
        self,
        session_id: str,
        check_challenge_expiry: bool = True
    ) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
        """
        Validate session is active and not expired
        
        Args:
            session_id: Session identifier
            check_challenge_expiry: Check challenge TTL (not just session TTL)
        
        Returns:
            (is_valid, error_reason, session_data)
        """
        
        # Get session from Redis
        session_data = await self.redis.hgetall(f"session:{session_id}")
        
        if not session_data:
            # Fallback to Postgres
            async with self.postgres.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT * FROM verification_sessions WHERE session_id = $1",
                    session_id
                )
            
            if not row:
                return False, "session_not_found", None
            
            session_data = dict(row)
        else:
            # Convert Redis data
            session_data = {k: v for k, v in session_data.items()}
        
        # Server time as authority
        now = datetime.utcnow()
        
        # Check session status
        if session_data.get("status") != SessionStatus.ACTIVE.value:
            return False, f"session_{session_data.get('status')}", session_data
        
        # Check session expiry
        session_expires_at = datetime.fromisoformat(session_data["session_expires_at"])
        if now > session_expires_at:
            await self._expire_session(session_id, "session_expired")
            return False, "session_expired", session_data
        
        # Check challenge expiry
        if check_challenge_expiry:
            challenge_expires_at = datetime.fromisoformat(session_data["challenge_expires_at"])
            if now > challenge_expires_at:
                await self._expire_session(session_id, "challenge_expired")
                return False, "challenge_expired", session_data
        
        # Check attempt limit
        attempts = int(session_data.get("attempts", 0))
        max_attempts = int(session_data.get("max_attempts", 3))
        
        if attempts >= max_attempts:
            await self._expire_session(session_id, "max_attempts_exceeded")
            return False, "max_attempts_exceeded", session_data
        
        # Check retry delay
        if session_data.get("next_retry_allowed_at"):
            next_retry = datetime.fromisoformat(session_data["next_retry_allowed_at"])
            if now < next_retry:
                retry_wait = (next_retry - now).total_seconds()
                return False, f"retry_delay_{int(retry_wait)}_seconds", session_data
        
        return True, None, session_data
    
    async def record_attempt(
        self,
        session_id: str,
        success: bool
    ) -> Dict[str, Any]:
        """
        Record verification attempt
        
        Args:
            session_id: Session identifier
            success: Whether attempt was successful
        
        Returns:
            Updated session data
        """
        
        # Validate session first
        is_valid, error, session_data = await self.validate_session(session_id)
        
        if not is_valid:
            raise SessionValidationException(error)
        
        # Server time
        now = datetime.utcnow()
        
        # Increment attempts
        attempts = int(session_data.get("attempts", 0)) + 1
        
        # Calculate retry delay (progressive backoff)
        next_retry_allowed_at = None
        if not success and attempts < self.config.max_attempts_per_session:
            # Progressive delay: 10s, 20s, 40s, ...
            delay = min(
                self.config.retry_delay_after_fail_seconds * (
                    self.config.retry_delay_multiplier ** (attempts - 1)
                ),
                self.config.max_retry_delay_seconds
            )
            next_retry_allowed_at = now + timedelta(seconds=delay)
        
        # Update status
        if success:
            status = SessionStatus.COMPLETED.value
        elif attempts >= self.config.max_attempts_per_session:
            status = SessionStatus.RATE_LIMITED.value
        else:
            status = SessionStatus.ACTIVE.value
        
        # Update Redis
        update_data = {
            "attempts": str(attempts),
            "status": status,
            "last_attempt_at": now.isoformat()
        }
        
        if next_retry_allowed_at:
            update_data["next_retry_allowed_at"] = next_retry_allowed_at.isoformat()
        
        await self.redis.hset(
            f"session:{session_id}",
            mapping=update_data
        )
        
        # Update Postgres
        async with self.postgres.acquire() as conn:
            await conn.execute(
                """
                UPDATE verification_sessions
                SET attempts = $1,
                    status = $2,
                    last_attempt_at = $3,
                    next_retry_allowed_at = $4,
                    updated_at = $5
                WHERE session_id = $6
                """,
                attempts,
                status,
                now,
                next_retry_allowed_at,
                now,
                session_id
            )
            
            # Record attempt in history
            await conn.execute(
                """
                INSERT INTO session_attempt_history
                (session_id, attempt_number, success, attempted_at)
                VALUES ($1, $2, $3, $4)
                """,
                session_id,
                attempts,
                success,
                now
            )
        
        # Update rate limit counters
        device_id = session_data["device_id"]
        ip_address = session_data["ip_address"]
        await self._increment_rate_counters(device_id, ip_address)
        
        logger.info(
            f"📊 Attempt recorded: {session_id}\n"
            f"   Attempt: {attempts}/{self.config.max_attempts_per_session}\n"
            f"   Success: {success}\n"
            f"   Status: {status}"
        )
        
        # Return updated session
        session_data.update(update_data)
        return session_data
    
    async def _check_rate_limits(
        self,
        device_id: str,
        ip_address: str
    ) -> Tuple[bool, Optional[str]]:
        """
        Check rate limits for device and IP
        
        Returns:
            (is_limited, reason)
        """
        
        # Check device hourly
        device_hourly_key = f"rate_limit:device:hourly:{device_id}"
        device_hourly = await self.redis.get(device_hourly_key)
        
        if device_hourly and int(device_hourly) >= self.config.max_attempts_per_device_hourly:
            return True, f"device_hourly_limit_{self.config.max_attempts_per_device_hourly}"
        
        # Check device daily
        device_daily_key = f"rate_limit:device:daily:{device_id}"
        device_daily = await self.redis.get(device_daily_key)
        
        if device_daily and int(device_daily) >= self.config.max_attempts_per_device_daily:
            return True, f"device_daily_limit_{self.config.max_attempts_per_device_daily}"
        
        # Check IP hourly
        ip_hourly_key = f"rate_limit:ip:hourly:{ip_address}"
        ip_hourly = await self.redis.get(ip_hourly_key)
        
        if ip_hourly and int(ip_hourly) >= self.config.max_attempts_per_ip_hourly:
            return True, f"ip_hourly_limit_{self.config.max_attempts_per_ip_hourly}"
        
        # Check IP daily
        ip_daily_key = f"rate_limit:ip:daily:{ip_address}"
        ip_daily = await self.redis.get(ip_daily_key)
        
        if ip_daily and int(ip_daily) >= self.config.max_attempts_per_ip_daily:
            return True, f"ip_daily_limit_{self.config.max_attempts_per_ip_daily}"
        
        return False, None
    
    async def _increment_rate_counters(
        self,
        device_id: str,
        ip_address: str
    ):
        """Increment rate limit counters"""
        
        # Device counters
        device_hourly_key = f"rate_limit:device:hourly:{device_id}"
        device_daily_key = f"rate_limit:device:daily:{device_id}"
        
        await self.redis.incr(device_hourly_key)
        await self.redis.expire(device_hourly_key, 3600)  # 1 hour
        
        await self.redis.incr(device_daily_key)
        await self.redis.expire(device_daily_key, 86400)  # 24 hours
        
        # IP counters
        ip_hourly_key = f"rate_limit:ip:hourly:{ip_address}"
        ip_daily_key = f"rate_limit:ip:daily:{ip_address}"
        
        await self.redis.incr(ip_hourly_key)
        await self.redis.expire(ip_hourly_key, 3600)
        
        await self.redis.incr(ip_daily_key)
        await self.redis.expire(ip_daily_key, 86400)
    
    async def _expire_session(
        self,
        session_id: str,
        reason: str
    ):
        """Mark session as expired"""
        
        await self.redis.hset(
            f"session:{session_id}",
            "status",
            SessionStatus.EXPIRED.value
        )
        
        async with self.postgres.acquire() as conn:
            await conn.execute(
                """
                UPDATE verification_sessions
                SET status = $1,
                    expired_reason = $2,
                    updated_at = $3
                WHERE session_id = $4
                """,
                SessionStatus.EXPIRED.value,
                reason,
                datetime.utcnow(),
                session_id
            )
    
    def _generate_session_id(self) -> str:
        """Generate cryptographically secure session ID"""
        timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        random_suffix = secrets.token_hex(8)
        return f"SES-{timestamp}-{random_suffix}"
    
    async def get_session_metrics(
        self,
        device_id: Optional[str] = None,
        ip_address: Optional[str] = None,
        hours: int = 24
    ) -> Dict[str, Any]:
        """
        Get session and attempt metrics
        
        Args:
            device_id: Filter by device
            ip_address: Filter by IP
            hours: Time window
        
        Returns:
            Metrics dictionary
        """
        
        since = datetime.utcnow() - timedelta(hours=hours)
        
        where_clauses = ["created_at >= $1"]
        params = [since]
        param_idx = 2
        
        if device_id:
            where_clauses.append(f"device_id = ${param_idx}")
            params.append(device_id)
            param_idx += 1
        
        if ip_address:
            where_clauses.append(f"ip_address = ${param_idx}")
            params.append(ip_address)
            param_idx += 1
        
        query = f"""
            SELECT 
                COUNT(*) as total_sessions,
                COUNT(*) FILTER (WHERE status = 'completed') as completed,
                COUNT(*) FILTER (WHERE status = 'expired') as expired,
                COUNT(*) FILTER (WHERE status = 'rate_limited') as rate_limited,
                AVG(attempts) as avg_attempts,
                SUM(attempts) as total_attempts
            FROM verification_sessions
            WHERE {' AND '.join(where_clauses)}
        """
        
        async with self.postgres.acquire() as conn:
            row = await conn.fetchrow(query, *params)
        
        return {
            "time_window_hours": hours,
            "total_sessions": row["total_sessions"] or 0,
            "completed": row["completed"] or 0,
            "expired": row["expired"] or 0,
            "rate_limited": row["rate_limited"] or 0,
            "avg_attempts": float(row["avg_attempts"] or 0),
            "total_attempts": row["total_attempts"] or 0,
            "device_id": device_id,
            "ip_address": ip_address
        }


class RateLimitException(Exception):
    """Rate limit exceeded"""
    pass


class SessionValidationException(Exception):
    """Session validation failed"""
    pass