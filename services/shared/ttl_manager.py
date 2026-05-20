"""
TTL (Time-To-Live) Policy Manager
Manages expiration policies for transient data
"""

import redis.asyncio as redis
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class TTLPolicy(str, Enum):
    """TTL policy types"""
    SESSION = "session"                      # 30 minutes
    RATE_LIMIT = "rate_limit"               # 1 hour
    CHALLENGE = "challenge"                  # 10 minutes
    JOB_LOCK = "job_lock"                   # 5 minutes
    RESULT_CACHE = "result_cache"           # 7 days
    IDEMPOTENCY = "idempotency"             # 24 hours
    VERIFICATION_STATE = "verification_state" # 15 minutes
    TEMPORARY_TOKEN = "temporary_token"      # 1 hour


class TTLManager:
    """
    TTL Policy Manager
    
    Manages expiration for ephemeral data in Redis:
    - Sessions: 30 minutes
    - Rate limits: 1 hour
    - Challenges: 10 minutes
    - Job locks: 5 minutes
    - Result cache: 7 days
    - Idempotency keys: 24 hours
    - Verification state: 15 minutes
    - Temporary tokens: 1 hour
    
    Features:
    - Automatic expiration
    - TTL extension
    - Cleanup monitoring
    - Memory optimization
    """
    
    # TTL durations in seconds
    TTL_DURATIONS = {
        TTLPolicy.SESSION: 1800,              # 30 minutes
        TTLPolicy.RATE_LIMIT: 3600,           # 1 hour
        TTLPolicy.CHALLENGE: 600,             # 10 minutes
        TTLPolicy.JOB_LOCK: 300,              # 5 minutes
        TTLPolicy.RESULT_CACHE: 604800,       # 7 days
        TTLPolicy.IDEMPOTENCY: 86400,         # 24 hours
        TTLPolicy.VERIFICATION_STATE: 900,    # 15 minutes
        TTLPolicy.TEMPORARY_TOKEN: 3600       # 1 hour
    }
    
    def __init__(self, redis_client: redis.Redis):
        self.redis = redis_client
    
    async def set_with_ttl(
        self,
        key: str,
        value: Any,
        policy: TTLPolicy
    ):
        """
        Set key with automatic TTL based on policy
        
        Args:
            key: Redis key
            value: Value to store
            policy: TTL policy to apply
        """
        
        ttl_seconds = self.TTL_DURATIONS[policy]
        
        await self.redis.setex(
            key,
            ttl_seconds,
            value
        )
        
        logger.debug(
            f"Set key with TTL: {key} "
            f"(policy: {policy.value}, ttl: {ttl_seconds}s)"
        )
    
    async def extend_ttl(
        self,
        key: str,
        policy: TTLPolicy
    ) -> bool:
        """
        Extend TTL for existing key
        
        Args:
            key: Redis key
            policy: TTL policy to apply
        
        Returns:
            True if TTL extended
        """
        
        ttl_seconds = self.TTL_DURATIONS[policy]
        
        result = await self.redis.expire(key, ttl_seconds)
        
        if result:
            logger.debug(f"Extended TTL for key: {key} ({ttl_seconds}s)")
        else:
            logger.warning(f"Failed to extend TTL for key: {key} (key not found)")
        
        return result
    
    async def get_ttl(self, key: str) -> Optional[int]:
        """
        Get remaining TTL for key
        
        Args:
            key: Redis key
        
        Returns:
            Remaining TTL in seconds, or None if key doesn't exist
        """
        
        ttl = await self.redis.ttl(key)
        
        if ttl == -2:
            # Key doesn't exist
            return None
        elif ttl == -1:
            # Key exists but has no TTL
            return -1
        else:
            return ttl
    
    async def set_session(
        self,
        session_id: str,
        session_data: Dict[str, Any]
    ):
        """
        Store session data with 30-minute TTL
        
        Args:
            session_id: Session identifier
            session_data: Session data
        """
        
        import json
        
        await self.set_with_ttl(
            f"session:{session_id}",
            json.dumps(session_data),
            TTLPolicy.SESSION
        )
    
    async def extend_session(self, session_id: str) -> bool:
        """
        Extend session TTL (refresh on activity)
        
        Args:
            session_id: Session identifier
        
        Returns:
            True if session extended
        """
        
        return await self.extend_ttl(
            f"session:{session_id}",
            TTLPolicy.SESSION
        )
    
    async def set_rate_limit(
        self,
        identifier: str,
        endpoint: str,
        count: int
    ):
        """
        Set rate limit counter with 1-hour TTL
        
        Args:
            identifier: Rate limit identifier (IP, user, etc.)
            endpoint: API endpoint
            count: Request count
        """
        
        await self.set_with_ttl(
            f"rate_limit:{identifier}:{endpoint}",
            str(count),
            TTLPolicy.RATE_LIMIT
        )
    
    async def set_challenge(
        self,
        challenge_id: str,
        challenge_data: Dict[str, Any]
    ):
        """
        Store challenge data with 10-minute TTL
        
        Args:
            challenge_id: Challenge identifier
            challenge_data: Challenge data
        """
        
        import json
        
        await self.set_with_ttl(
            f"challenge:{challenge_id}",
            json.dumps(challenge_data),
            TTLPolicy.CHALLENGE
        )
    
    async def set_job_lock(
        self,
        job_id: str,
        worker_id: str
    ):
        """
        Set job processing lock with 5-minute TTL
        
        Args:
            job_id: Job identifier
            worker_id: Worker identifier
        """
        
        await self.set_with_ttl(
            f"jobs:processing:{job_id}",
            worker_id,
            TTLPolicy.JOB_LOCK
        )
    
    async def set_result_cache(
        self,
        job_id: str,
        result: Dict[str, Any]
    ):
        """
        Cache job result with 7-day TTL
        
        Args:
            job_id: Job identifier
            result: Job result
        """
        
        import json
        
        await self.set_with_ttl(
            f"jobs:result:{job_id}",
            json.dumps(result),
            TTLPolicy.RESULT_CACHE
        )
    
    async def set_idempotency_key(
        self,
        idempotency_key: str,
        response: Dict[str, Any]
    ):
        """
        Store idempotency response with 24-hour TTL
        
        Args:
            idempotency_key: Idempotency key
            response: API response to cache
        """
        
        import json
        
        await self.set_with_ttl(
            f"idempotency:{idempotency_key}",
            json.dumps(response),
            TTLPolicy.IDEMPOTENCY
        )
    
    async def get_ttl_statistics(self) -> Dict[str, Any]:
        """
        Get TTL policy statistics
        
        Returns:
            TTL statistics for each policy
        """
        
        stats = {}
        
        for policy in TTLPolicy:
            # Get keys matching this policy
            pattern = f"{policy.value}:*"
            
            keys = []
            async for key in self.redis.scan_iter(match=pattern, count=100):
                keys.append(key)
            
            total_keys = len(keys)
            
            # Sample TTLs
            ttls = []
            for key in keys[:100]:  # Sample first 100
                ttl = await self.redis.ttl(key)
                if ttl > 0:
                    ttls.append(ttl)
            
            avg_ttl = sum(ttls) / len(ttls) if ttls else 0
            
            stats[policy.value] = {
                "total_keys": total_keys,
                "target_ttl_seconds": self.TTL_DURATIONS[policy],
                "avg_remaining_ttl_seconds": avg_ttl,
                "sampled_keys": len(ttls)
            }
        
        return stats
    
    async def cleanup_expired_keys(self) -> int:
        """
        Manually trigger cleanup of expired keys
        
        Returns:
            Number of keys cleaned up
        """
        
        # Redis automatically removes expired keys, but we can force it
        # by scanning and checking TTL
        
        cleaned = 0
        
        async for key in self.redis.scan_iter(count=1000):
            ttl = await self.redis.ttl(key)
            
            if ttl == -2:
                # Key expired but not yet removed
                await self.redis.delete(key)
                cleaned += 1
        
        logger.info(f"🧹 Cleanup completed: {cleaned} expired keys removed")
        
        return cleaned