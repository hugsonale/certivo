"""
Safe Database Access Layer
100% parameterized queries - ZERO raw SQL
"""

import asyncpg
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime


class SafeDatabaseAccess:
    """
    Database access layer with 100% parameterized queries
    
    RULES:
    1. NEVER use string interpolation or f-strings in SQL
    2. ALWAYS use parameterized queries ($1, $2, etc.)
    3. NEVER construct SQL dynamically from user input
    4. Use prepared statements for repeated queries
    """
    
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool
    
    # ========================================================================
    # CHALLENGE OPERATIONS
    # ========================================================================
    
    async def create_challenge(
        self,
        challenge_id: str,
        device_id: str,
        nonce: str,
        session_metadata: str,
        watermark_seed: str,
        expires_at: datetime
    ) -> bool:
        """
        Create challenge record (parameterized)
        
        ❌ WRONG:
            query = f"INSERT INTO challenges (challenge_id) VALUES ('{challenge_id}')"
        
        ✅ CORRECT:
            query = "INSERT INTO challenges (challenge_id) VALUES ($1)"
            await conn.execute(query, challenge_id)
        """
        
        query = """
            INSERT INTO challenges 
            (challenge_id, device_id, nonce, session_metadata, watermark_seed, 
             expires_at, consumed, created_at)
            VALUES ($1, $2, $3, $4, $5, $6, false, $7)
        """
        
        async with self.pool.acquire() as conn:
            try:
                await conn.execute(
                    query,
                    challenge_id,
                    device_id,
                    nonce,
                    session_metadata,
                    watermark_seed,
                    expires_at,
                    datetime.utcnow()
                )
                return True
            except Exception as e:
                print(f"Database error: {e}")
                return False
    
    async def get_challenge(
        self,
        challenge_id: str
    ) -> Optional[Dict[str, Any]]:
        """Get challenge by ID (parameterized)"""
        
        query = """
            SELECT challenge_id, device_id, nonce, consumed, 
                   expires_at, session_metadata
            FROM challenges
            WHERE challenge_id = $1
        """
        
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(query, challenge_id)
            
            if row:
                return dict(row)
            return None
    
    async def mark_challenge_consumed(
        self,
        challenge_id: str,
        consumed_at: float,
        device_id: str
    ) -> bool:
        """Mark challenge as consumed (parameterized)"""
        
        query = """
            UPDATE challenges
            SET consumed = true,
                consumed_at = $1,
                consumed_by_device = $2
            WHERE challenge_id = $3 AND consumed = false
        """
        
        async with self.pool.acquire() as conn:
            result = await conn.execute(query, consumed_at, device_id, challenge_id)
            
            # Check if row was updated
            return result.split()[-1] == "1"
    
    # ========================================================================
    # SESSION OPERATIONS
    # ========================================================================
    
    async def create_session(
        self,
        session_id: str,
        device_id: str,
        trust_score: float,
        trust_level: str,
        total_challenges: int
    ) -> bool:
        """Create verification session (parameterized)"""
        
        query = """
            INSERT INTO sessions
            (session_id, device_id, trust_score, trust_level, 
             total_challenges, timestamp_utc)
            VALUES ($1, $2, $3, $4, $5, $6)
        """
        
        async with self.pool.acquire() as conn:
            try:
                await conn.execute(
                    query,
                    session_id,
                    device_id,
                    trust_score,
                    trust_level,
                    total_challenges,
                    datetime.utcnow()
                )
                return True
            except Exception as e:
                print(f"Database error: {e}")
                return False
    
    async def get_device_sessions(
        self,
        device_id: str,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Get recent sessions for device (parameterized)"""
        
        query = """
            SELECT session_id, trust_score, trust_level, timestamp_utc
            FROM sessions
            WHERE device_id = $1
            ORDER BY timestamp_utc DESC
            LIMIT $2
        """
        
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, device_id, limit)
            return [dict(row) for row in rows]
    
    # ========================================================================
    # VERIFICATION OUTCOMES (FAR/FRR)
    # ========================================================================
    
    async def record_verification_outcome(
        self,
        session_id: str,
        device_id: str,
        is_genuine: bool,
        was_accepted: bool,
        outcome_type: str,
        liveness_score: float,
        metadata: str
    ) -> bool:
        """Record verification outcome (parameterized)"""
        
        query = """
            INSERT INTO verification_outcomes
            (session_id, device_id, is_genuine, was_accepted, 
             outcome_type, liveness_score, metadata, timestamp_utc)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        """
        
        async with self.pool.acquire() as conn:
            try:
                await conn.execute(
                    query,
                    session_id,
                    device_id,
                    is_genuine,
                    was_accepted,
                    outcome_type,
                    liveness_score,
                    metadata,
                    datetime.utcnow()
                )
                return True
            except Exception as e:
                print(f"Database error: {e}")
                return False
    
    # ========================================================================
    # ADMIN OPERATIONS
    # ========================================================================
    
    async def revoke_device_trust(
        self,
        device_id: str,
        reason: str
    ) -> bool:
        """Revoke device trust (parameterized)"""
        
        query = """
            UPDATE trusted_devices
            SET trust_revoked = true,
                revoked_at = $1,
                revocation_reason = $2
            WHERE device_id = $3
        """
        
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                query,
                datetime.utcnow(),
                reason,
                device_id
            )
            return result.split()[-1] == "1"
    
    # ========================================================================
    # SEARCH WITH SAFE FILTERS
    # ========================================================================
    
    async def search_sessions(
        self,
        device_id: Optional[str] = None,
        trust_level: Optional[str] = None,
        min_trust_score: Optional[float] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Search sessions with optional filters (safe parameterization)
        
        Dynamic WHERE clause construction - SAFE METHOD
        """
        
        # Build query parts
        where_clauses = []
        params = []
        param_idx = 1
        
        if device_id:
            where_clauses.append(f"device_id = ${param_idx}")
            params.append(device_id)
            param_idx += 1
        
        if trust_level:
            where_clauses.append(f"trust_level = ${param_idx}")
            params.append(trust_level)
            param_idx += 1
        
        if min_trust_score is not None:
            where_clauses.append(f"trust_score >= ${param_idx}")
            params.append(min_trust_score)
            param_idx += 1
        
        # Construct query safely
        query = "SELECT * FROM sessions"
        
        if where_clauses:
            query += " WHERE " + " AND ".join(where_clauses)
        
        query += f" ORDER BY timestamp_utc DESC LIMIT ${param_idx}"
        params.append(limit)
        
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, *params)
            return [dict(row) for row in rows]