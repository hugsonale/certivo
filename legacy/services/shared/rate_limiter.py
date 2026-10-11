"""
Multi-dimensional distributed rate limiting
Supports: IP, subnet, ASN, device fingerprint, account, session, challenge ID
"""

import redis.asyncio as redis
import ipaddress
import hashlib
import time
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime, timedelta
from enum import Enum


class RateLimitDimension(str, Enum):
    """Rate limiting dimensions"""
    IP = "ip"
    SUBNET = "subnet"
    ASN = "asn"
    DEVICE = "device"
    ACCOUNT = "account"
    SESSION = "session"
    CHALLENGE = "challenge"


class PenaltyLevel(str, Enum):
    """Progressive penalty levels"""
    NONE = "none"
    SOFT_THROTTLE = "soft_throttle"  # Slowdown
    HARD_BLOCK = "hard_block"         # Reject
    TEMPORARY_BAN = "temporary_ban"   # Extended ban


class RateLimitConfig:
    """Rate limit configuration per dimension"""
    
    def __init__(
        self,
        dimension: RateLimitDimension,
        max_requests: int,
        window_seconds: int,
        soft_throttle_at: Optional[int] = None,
        hard_block_at: Optional[int] = None,
        ban_duration_seconds: int = 3600
    ):
        self.dimension = dimension
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.soft_throttle_at = soft_throttle_at or int(max_requests * 0.7)
        self.hard_block_at = hard_block_at or max_requests
        self.ban_duration_seconds = ban_duration_seconds


# Default rate limit configurations
DEFAULT_LIMITS = {
    RateLimitDimension.IP: RateLimitConfig(
        dimension=RateLimitDimension.IP,
        max_requests=100,
        window_seconds=60,
        soft_throttle_at=70,
        hard_block_at=100,
        ban_duration_seconds=3600  # 1 hour ban
    ),
    RateLimitDimension.SUBNET: RateLimitConfig(
        dimension=RateLimitDimension.SUBNET,
        max_requests=500,
        window_seconds=60,
        soft_throttle_at=350,
        hard_block_at=500,
        ban_duration_seconds=7200  # 2 hour ban
    ),
    RateLimitDimension.ASN: RateLimitConfig(
        dimension=RateLimitDimension.ASN,
        max_requests=1000,
        window_seconds=60,
        soft_throttle_at=700,
        hard_block_at=1000,
        ban_duration_seconds=14400  # 4 hour ban
    ),
    RateLimitDimension.DEVICE: RateLimitConfig(
        dimension=RateLimitDimension.DEVICE,
        max_requests=10,
        window_seconds=60,
        soft_throttle_at=7,
        hard_block_at=10,
        ban_duration_seconds=1800  # 30 min ban
    ),
    RateLimitDimension.SESSION: RateLimitConfig(
        dimension=RateLimitDimension.SESSION,
        max_requests=5,
        window_seconds=300,  # 5 minutes
        soft_throttle_at=4,
        hard_block_at=5,
        ban_duration_seconds=600  # 10 min ban
    ),
    RateLimitDimension.CHALLENGE: RateLimitConfig(
        dimension=RateLimitDimension.CHALLENGE,
        max_requests=3,
        window_seconds=300,  # 5 minutes
        soft_throttle_at=2,
        hard_block_at=3,
        ban_duration_seconds=900  # 15 min ban
    )
}


class DistributedRateLimiter:
    """
    Distributed rate limiter using Redis
    Ensures consistency across multiple API replicas
    """
    
    def __init__(self, redis_client: redis.Redis):
        self.redis = redis_client
        self.limits = DEFAULT_LIMITS
    
    def _make_key(self, dimension: RateLimitDimension, identifier: str) -> str:
        """Create Redis key for rate limit tracking"""
        # Hash identifier for consistent key length
        id_hash = hashlib.sha256(identifier.encode()).hexdigest()[:16]
        return f"ratelimit:{dimension.value}:{id_hash}"
    
    def _make_ban_key(self, dimension: RateLimitDimension, identifier: str) -> str:
        """Create Redis key for ban tracking"""
        id_hash = hashlib.sha256(identifier.encode()).hexdigest()[:16]
        return f"ban:{dimension.value}:{id_hash}"
    
    def _get_subnet(self, ip: str, prefix_length: int = 24) -> str:
        """Get subnet from IP address"""
        try:
            ip_obj = ipaddress.ip_address(ip)
            if ip_obj.version == 4:
                network = ipaddress.ip_network(f"{ip}/{prefix_length}", strict=False)
            else:
                network = ipaddress.ip_network(f"{ip}/64", strict=False)
            return str(network)
        except Exception:
            return ip
    
    async def _increment_counter(
        self,
        dimension: RateLimitDimension,
        identifier: str
    ) -> Tuple[int, int]:
        """
        Increment request counter atomically
        Returns: (current_count, ttl_seconds)
        """
        config = self.limits[dimension]
        key = self._make_key(dimension, identifier)
        
        # Use Redis pipeline for atomic operations
        pipe = self.redis.pipeline()
        
        # Increment counter
        pipe.incr(key)
        
        # Set expiry only if key is new
        pipe.expire(key, config.window_seconds, nx=True)
        
        # Get TTL
        pipe.ttl(key)
        
        results = await pipe.execute()
        
        current_count = results[0]
        ttl = results[2]
        
        return current_count, ttl
    
    async def _check_ban(
        self,
        dimension: RateLimitDimension,
        identifier: str
    ) -> Optional[int]:
        """
        Check if identifier is banned
        Returns: remaining ban time in seconds, or None if not banned
        """
        ban_key = self._make_ban_key(dimension, identifier)
        ttl = await self.redis.ttl(ban_key)
        
        if ttl > 0:
            return ttl
        
        return None
    
    async def _apply_ban(
        self,
        dimension: RateLimitDimension,
        identifier: str
    ):
        """Apply temporary ban"""
        config = self.limits[dimension]
        ban_key = self._make_ban_key(dimension, identifier)
        
        await self.redis.setex(
            ban_key,
            config.ban_duration_seconds,
            "banned"
        )
    
    async def check_rate_limit(
        self,
        dimension: RateLimitDimension,
        identifier: str,
        increment: bool = True
    ) -> Dict[str, Any]:
        """
        Check rate limit for a dimension
        
        Returns:
        {
            "allowed": bool,
            "penalty_level": PenaltyLevel,
            "current_count": int,
            "limit": int,
            "reset_in": int,
            "retry_after": int (if blocked)
        }
        """
        config = self.limits[dimension]
        
        # Check if banned
        ban_ttl = await self._check_ban(dimension, identifier)
        if ban_ttl:
            return {
                "allowed": False,
                "penalty_level": PenaltyLevel.TEMPORARY_BAN,
                "current_count": config.hard_block_at,
                "limit": config.max_requests,
                "reset_in": ban_ttl,
                "retry_after": ban_ttl,
                "reason": f"Temporary ban for {dimension.value}"
            }
        
        # Increment counter if requested
        if increment:
            current_count, ttl = await self._increment_counter(dimension, identifier)
        else:
            key = self._make_key(dimension, identifier)
            current_count = await self.redis.get(key)
            current_count = int(current_count) if current_count else 0
            ttl = await self.redis.ttl(key)
        
        # Determine penalty level
        penalty_level = PenaltyLevel.NONE
        allowed = True
        retry_after = 0
        
        if current_count >= config.hard_block_at:
            # Hard block - apply ban
            penalty_level = PenaltyLevel.HARD_BLOCK
            allowed = False
            retry_after = ttl
            
            # Apply temporary ban
            await self._apply_ban(dimension, identifier)
            
        elif current_count >= config.soft_throttle_at:
            # Soft throttle - add delay
            penalty_level = PenaltyLevel.SOFT_THROTTLE
            allowed = True  # Still allowed but throttled
        
        return {
            "allowed": allowed,
            "penalty_level": penalty_level,
            "current_count": current_count,
            "limit": config.max_requests,
            "reset_in": ttl if ttl > 0 else config.window_seconds,
            "retry_after": retry_after,
            "dimension": dimension.value
        }
    
    async def check_multi_dimensional(
        self,
        dimensions: Dict[RateLimitDimension, str]
    ) -> Dict[str, Any]:
        """
        Check multiple dimensions simultaneously
        Returns most restrictive result
        
        Args:
            dimensions: {RateLimitDimension.IP: "1.2.3.4", ...}
        """
        results = []
        
        for dimension, identifier in dimensions.items():
            result = await self.check_rate_limit(dimension, identifier)
            results.append(result)
        
        # Find most restrictive
        blocked = [r for r in results if not r["allowed"]]
        
        if blocked:
            # Return most severe block (longest retry_after)
            return max(blocked, key=lambda x: x["retry_after"])
        
        # Check for soft throttle
        throttled = [r for r in results if r["penalty_level"] == PenaltyLevel.SOFT_THROTTLE]
        
        if throttled:
            return max(throttled, key=lambda x: x["current_count"])
        
        # All allowed
        return {
            "allowed": True,
            "penalty_level": PenaltyLevel.NONE,
            "dimensions_checked": list(dimensions.keys())
        }
    
    async def get_metrics(
        self,
        dimension: RateLimitDimension,
        identifier: str
    ) -> Dict[str, Any]:
        """Get current metrics for a dimension"""
        key = self._make_key(dimension, identifier)
        ban_key = self._make_ban_key(dimension, identifier)
        
        count = await self.redis.get(key)
        ttl = await self.redis.ttl(key)
        is_banned = await self.redis.exists(ban_key)
        
        return {
            "dimension": dimension.value,
            "identifier": identifier,
            "current_count": int(count) if count else 0,
            "reset_in": ttl if ttl > 0 else 0,
            "is_banned": bool(is_banned)
        }