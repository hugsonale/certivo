"""
Redis caching layer for performance optimization
"""
import redis
import json
from typing import Optional, Any
import os

# Connect to Redis (install and run Redis server first)
try:
    redis_client = redis.Redis(
        host=os.getenv('REDIS_HOST', 'localhost'),
        port=int(os.getenv('REDIS_PORT', 6379)),
        db=0,
        decode_responses=True
    )
    redis_client.ping()
    REDIS_AVAILABLE = True
    print("✅ Redis cache connected")
except:
    REDIS_AVAILABLE = False
    redis_client = None
    print("⚠️  Redis not available - caching disabled")


def cache_get(key: str) -> Optional[Any]:
    """Get value from cache"""
    if not REDIS_AVAILABLE:
        return None
    
    try:
        value = redis_client.get(key)
        if value:
            return json.loads(value)
    except:
        pass
    return None


def cache_set(key: str, value: Any, ttl: int = 300):
    """Set value in cache with TTL (default 5 minutes)"""
    if not REDIS_AVAILABLE:
        return
    
    try:
        redis_client.setex(key, ttl, json.dumps(value))
    except:
        pass


def cache_delete(key: str):
    """Delete key from cache"""
    if not REDIS_AVAILABLE:
        return
    
    try:
        redis_client.delete(key)
    except:
        pass