"""
One-time consume semantics with distributed transaction
Ensures tokens can only be used once across all replicas
"""

import redis.asyncio as redis
import asyncpg
from typing import Optional, Dict, Any
import time
import uuid


class OneTimeConsumeManager:
    """
    Manage one-time token consumption with strong consistency
    Uses Redis for fast distributed locking + Postgres for durability
    """
    
    def __init__(
        self,
        redis_client: redis.Redis,
        postgres_pool: asyncpg.Pool
    ):
        self.redis = redis_client
        self.postgres = postgres_pool
        self.lock_timeout = 10  # seconds
    
    async def try_consume_token(
        self,
        token_id: str,
        challenge_id: str,
        device_id: str,
        metadata: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Attempt to consume a token (one-time use)
        
        Returns:
            {
                "consumed": bool,
                "error": str (if failed),
                "consumed_at": timestamp (if successful)
            }
        """
        
        # Step 1: Acquire distributed lock in Redis
        lock_acquired = await self._acquire_consume_lock(token_id)
        
        if not lock_acquired:
            return {
                "consumed": False,
                "error": "Token is being consumed by another request"
            }
        
        try:
            # Step 2: Check if already consumed (Redis cache)
            redis_consumed = await self._check_redis_consumed(token_id)
            if redis_consumed:
                return {
                    "consumed": False,
                    "error": "Token has already been consumed"
                }
            
            # Step 3: Check if already consumed (Postgres - source of truth)
            postgres_consumed = await self._check_postgres_consumed(challenge_id)
            if postgres_consumed:
                # Update Redis cache
                await self._mark_redis_consumed(token_id)
                return {
                    "consumed": False,
                    "error": "Token has already been consumed"
                }
            
            # Step 4: Mark as consumed in both Redis and Postgres (transaction)
            consumed_at = await self._execute_consume_transaction(
                token_id=token_id,
                challenge_id=challenge_id,
                device_id=device_id,
                metadata=metadata
            )
            
            return {
                "consumed": True,
                "consumed_at": consumed_at
            }
            
        finally:
            # Always release lock
            await self._release_consume_lock(token_id)
    
    async def _acquire_consume_lock(self, token_id: str) -> bool:
        """
        Acquire distributed lock for token consumption
        
        Returns:
            True if lock acquired, False otherwise
        """
        
        lock_key = f"consume_lock:{token_id}"
        lock_value = str(uuid.uuid4())
        
        # Try to acquire lock with NX (only if not exists) and EX (expiry)
        acquired = await self.redis.set(
            lock_key,
            lock_value,
            nx=True,
            ex=self.lock_timeout
        )
        
        return bool(acquired)
    
    async def _release_consume_lock(self, token_id: str):
        """Release distributed lock"""
        lock_key = f"consume_lock:{token_id}"
        await self.redis.delete(lock_key)
    
    async def _check_redis_consumed(self, token_id: str) -> bool:
        """Check if token marked as consumed in Redis"""
        consumed_key = f"consumed:{token_id}"
        exists = await self.redis.exists(consumed_key)
        return bool(exists)
    
    async def _mark_redis_consumed(self, token_id: str):
        """Mark token as consumed in Redis"""
        consumed_key = f"consumed:{token_id}"
        # Set with 24 hour TTL
        await self.redis.setex(consumed_key, 86400, "1")
    
    async def _check_postgres_consumed(self, challenge_id: str) -> bool:
        """Check if challenge marked as consumed in Postgres"""
        async with self.postgres.acquire() as conn:
            result = await conn.fetchval(
                """
                SELECT consumed FROM challenges 
                WHERE challenge_id = $1
                """,
                challenge_id
            )
            return bool(result) if result is not None else False
    
    async def _execute_consume_transaction(
        self,
        token_id: str,
        challenge_id: str,
        device_id: str,
        metadata: Dict[str, Any]
    ) -> float:
        """
        Execute consume transaction atomically
        Updates both Redis and Postgres
        
        Returns:
            Timestamp of consumption
        """
        
        consumed_at = time.time()
        
        # Postgres transaction
        async with self.postgres.acquire() as conn:
            async with conn.transaction():
                # Mark challenge as consumed
                await conn.execute(
                    """
                    UPDATE challenges 
                    SET consumed = true, 
                        consumed_at = $1,
                        consumed_by_device = $2,
                        consume_metadata = $3
                    WHERE challenge_id = $4
                    """,
                    consumed_at,
                    device_id,
                    str(metadata),
                    challenge_id
                )
                
                # Insert consumption record
                await conn.execute(
                    """
                    INSERT INTO token_consumptions
                    (token_id, challenge_id, device_id, consumed_at, metadata)
                    VALUES ($1, $2, $3, $4, $5)
                    """,
                    token_id,
                    challenge_id,
                    device_id,
                    consumed_at,
                    str(metadata)
                )
        
        # Mark in Redis cache
        await self._mark_redis_consumed(token_id)
        
        return consumed_at
    
    async def get_consumption_record(
        self,
        token_id: str
    ) -> Optional[Dict[str, Any]]:
        """Get consumption record for a token"""
        
        async with self.postgres.acquire() as conn:
            record = await conn.fetchrow(
                """
                SELECT token_id, challenge_id, device_id, consumed_at, metadata
                FROM token_consumptions
                WHERE token_id = $1
                """,
                token_id
            )
            
            if record:
                return dict(record)
            return None