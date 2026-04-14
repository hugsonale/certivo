"""
Idempotency key handling for safe retries
"""

import redis.asyncio as redis
import json
import hashlib
from typing import Optional, Dict, Any
from datetime import timedelta


class IdempotencyManager:
    """Manages idempotency keys for API endpoints"""
    
    def __init__(self, redis_client: redis.Redis):
        self.redis = redis_client
        self.ttl = timedelta(hours=24)  # Keys valid for 24 hours
    
    def _make_key(self, idempotency_key: str, endpoint: str) -> str:
        """Create Redis key for idempotency"""
        # Hash the idempotency key for consistent length
        key_hash = hashlib.sha256(idempotency_key.encode()).hexdigest()[:16]
        return f"idempotency:{endpoint}:{key_hash}"
    
    async def get_cached_response(
        self,
        idempotency_key: str,
        endpoint: str
    ) -> Optional[Dict[str, Any]]:
        """Retrieve cached response if exists"""
        key = self._make_key(idempotency_key, endpoint)
        
        cached = await self.redis.get(key)
        if cached:
            return json.loads(cached)
        
        return None
    
    async def cache_response(
        self,
        idempotency_key: str,
        endpoint: str,
        response: Dict[str, Any],
        status_code: int
    ):
        """Cache response for future identical requests"""
        key = self._make_key(idempotency_key, endpoint)
        
        cache_data = {
            "response": response,
            "status_code": status_code
        }
        
        await self.redis.setex(
            key,
            int(self.ttl.total_seconds()),
            json.dumps(cache_data)
        )
    
    async def is_processing(
        self,
        idempotency_key: str,
        endpoint: str
    ) -> bool:
        """Check if request is currently being processed"""
        lock_key = f"{self._make_key(idempotency_key, endpoint)}:lock"
        return await self.redis.exists(lock_key)
    
    async def acquire_lock(
        self,
        idempotency_key: str,
        endpoint: str,
        timeout: int = 60
    ) -> bool:
        """Acquire processing lock"""
        lock_key = f"{self._make_key(idempotency_key, endpoint)}:lock"
        
        # Set lock with timeout
        result = await self.redis.set(
            lock_key,
            "1",
            nx=True,  # Only set if not exists
            ex=timeout
        )
        
        return bool(result)
    
    async def release_lock(
        self,
        idempotency_key: str,
        endpoint: str
    ):
        """Release processing lock"""
        lock_key = f"{self._make_key(idempotency_key, endpoint)}:lock"
        await self.redis.delete(lock_key)