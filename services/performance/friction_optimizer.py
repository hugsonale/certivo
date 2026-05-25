"""
Friction Management & Performance Optimization
Target: <=20 seconds median time-to-complete
"""

import asyncio
import asyncpg
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
import statistics
import logging

logger = logging.getLogger(__name__)


class RiskLevel(str, Enum):
    """Risk levels for progressive trust"""
    VERY_LOW = "very_low"      # Returning user, good history
    LOW = "low"                # Known device, low-risk action
    MEDIUM = "medium"          # New user, standard action
    HIGH = "high"              # High-value transaction
    VERY_HIGH = "very_high"    # Suspicious activity detected


@dataclass
class PerformanceMetrics:
    """Performance tracking for time-to-complete"""
    session_id: str
    
    # Timing breakdown
    session_start: datetime
    consent_shown: Optional[datetime] = None
    consent_granted: Optional[datetime] = None
    challenge_issued: Optional[datetime] = None
    video_upload_start: Optional[datetime] = None
    video_upload_complete: Optional[datetime] = None
    processing_start: Optional[datetime] = None
    processing_complete: Optional[datetime] = None
    result_returned: Optional[datetime] = None
    
    # Calculated durations
    total_duration_ms: Optional[int] = None
    consent_duration_ms: Optional[int] = None
    upload_duration_ms: Optional[int] = None
    processing_duration_ms: Optional[int] = None
    
    # User experience
    success: bool = False
    abandonment: bool = False
    error_occurred: bool = False
    
    def calculate_durations(self):
        """Calculate all durations"""
        
        if self.result_returned:
            self.total_duration_ms = int(
                (self.result_returned - self.session_start).total_seconds() * 1000
            )
        
        if self.consent_granted and self.consent_shown:
            self.consent_duration_ms = int(
                (self.consent_granted - self.consent_shown).total_seconds() * 1000
            )
        
        if self.video_upload_complete and self.video_upload_start:
            self.upload_duration_ms = int(
                (self.video_upload_complete - self.video_upload_start).total_seconds() * 1000
            )
        
        if self.processing_complete and self.processing_start:
            self.processing_duration_ms = int(
                (self.processing_complete - self.processing_start).total_seconds() * 1000
            )


@dataclass
class ProgressiveTrustProfile:
    """Progressive trust configuration"""
    risk_level: RiskLevel
    
    # Challenge requirements
    challenge_count: int
    challenge_types: List[str]
    difficulty_level: str  # "easy", "medium", "hard"
    
    # Time targets
    target_duration_seconds: int
    
    # UI optimizations
    skip_intro: bool = False
    pre_cache_challenges: bool = False
    enable_fast_path: bool = False


class FrictionOptimizer:
    """
    Friction Management System
    
    Features:
    - Time-to-complete tracking
    - Progressive trust (risk-based friction)
    - Performance optimization
    - Adaptive difficulty
    
    Target: <=20 seconds median for successful users
    """
    
    # Progressive trust configurations
    TRUST_PROFILES = {
        RiskLevel.VERY_LOW: ProgressiveTrustProfile(
            risk_level=RiskLevel.VERY_LOW,
            challenge_count=1,
            challenge_types=["blink"],
            difficulty_level="easy",
            target_duration_seconds=10,
            skip_intro=True,
            pre_cache_challenges=True,
            enable_fast_path=True
        ),
        
        RiskLevel.LOW: ProgressiveTrustProfile(
            risk_level=RiskLevel.LOW,
            challenge_count=1,
            challenge_types=["head_turn_left", "blink"],
            difficulty_level="easy",
            target_duration_seconds=15,
            skip_intro=True,
            pre_cache_challenges=True,
            enable_fast_path=True
        ),
        
        RiskLevel.MEDIUM: ProgressiveTrustProfile(
            risk_level=RiskLevel.MEDIUM,
            challenge_count=2,
            challenge_types=["head_turn_left", "blink", "smile"],
            difficulty_level="medium",
            target_duration_seconds=20,
            skip_intro=False,
            pre_cache_challenges=True,
            enable_fast_path=False
        ),
        
        RiskLevel.HIGH: ProgressiveTrustProfile(
            risk_level=RiskLevel.HIGH,
            challenge_count=3,
            challenge_types=["head_turn_left", "head_turn_right", "blink", "smile"],
            difficulty_level="medium",
            target_duration_seconds=30,
            skip_intro=False,
            pre_cache_challenges=False,
            enable_fast_path=False
        ),
        
        RiskLevel.VERY_HIGH: ProgressiveTrustProfile(
            risk_level=RiskLevel.VERY_HIGH,
            challenge_count=4,
            challenge_types=[
                "head_turn_left", "head_turn_right",
                "blink", "smile", "nod", "raise_eyebrows"
            ],
            difficulty_level="hard",
            target_duration_seconds=45,
            skip_intro=False,
            pre_cache_challenges=False,
            enable_fast_path=False
        )
    }
    
    def __init__(self, postgres_pool: asyncpg.Pool):
        self.postgres = postgres_pool
    
    async def determine_risk_level(
        self,
        session_id: str,
        device_id: str,
        user_identifier: Optional[str] = None,
        transaction_value: Optional[float] = None,
        action_type: str = "login"
    ) -> RiskLevel:
        """
        Determine risk level for progressive trust
        
        Args:
            session_id: Session identifier
            device_id: Device fingerprint
            user_identifier: Optional user identifier
            transaction_value: Optional transaction value
            action_type: Type of action (login, payment, etc.)
        
        Returns:
            Risk level
        """
        
        risk_score = 0.0
        
        # Factor 1: User history
        if user_identifier:
            async with self.postgres.acquire() as conn:
                # Check successful verifications
                success_count = await conn.fetchval(
                    """
                    SELECT COUNT(*)
                    FROM verification_results
                    WHERE session_id IN (
                        SELECT session_id FROM sessions WHERE user_identifier = $1
                    )
                    AND decision = 'approve'
                    AND created_at >= NOW() - INTERVAL '30 days'
                    """,
                    user_identifier
                )
                
                # More history = lower risk
                if success_count >= 10:
                    risk_score -= 0.3
                elif success_count >= 5:
                    risk_score -= 0.2
                elif success_count >= 1:
                    risk_score -= 0.1
        
        # Factor 2: Device trust
        async with self.postgres.acquire() as conn:
            device_seen_count = await conn.fetchval(
                """
                SELECT COUNT(*)
                FROM sessions
                WHERE device_id = $1
                AND created_at >= NOW() - INTERVAL '30 days'
                """,
                device_id
            )
            
            # Known device = lower risk
            if device_seen_count >= 5:
                risk_score -= 0.2
            elif device_seen_count >= 2:
                risk_score -= 0.1
        
        # Factor 3: Transaction value
        if transaction_value:
            if transaction_value > 10000:
                risk_score += 0.4
            elif transaction_value > 1000:
                risk_score += 0.2
            elif transaction_value > 100:
                risk_score += 0.1
        
        # Factor 4: Action type
        high_risk_actions = ["payment", "withdrawal", "account_deletion"]
        if action_type in high_risk_actions:
            risk_score += 0.3
        
        # Factor 5: Time-based anomalies
        async with self.postgres.acquire() as conn:
            # Check for unusual activity patterns
            recent_sessions = await conn.fetchval(
                """
                SELECT COUNT(*)
                FROM sessions
                WHERE device_id = $1
                AND created_at >= NOW() - INTERVAL '1 hour'
                """,
                device_id
            )
            
            # Multiple sessions in short time = higher risk
            if recent_sessions > 5:
                risk_score += 0.2
        
        # Map score to risk level
        if risk_score <= -0.3:
            risk_level = RiskLevel.VERY_LOW
        elif risk_score <= 0:
            risk_level = RiskLevel.LOW
        elif risk_score <= 0.3:
            risk_level = RiskLevel.MEDIUM
        elif risk_score <= 0.6:
            risk_level = RiskLevel.HIGH
        else:
            risk_level = RiskLevel.VERY_HIGH
        
        logger.info(
            f"📊 Risk assessment:\n"
            f"   Session: {session_id}\n"
            f"   Risk score: {risk_score:.2f}\n"
            f"   Risk level: {risk_level.value}\n"
            f"   User history: {success_count if user_identifier else 0} successes\n"
            f"   Device trust: {device_seen_count} previous sessions"
        )
        
        return risk_level
    
    def get_trust_profile(self, risk_level: RiskLevel) -> ProgressiveTrustProfile:
        """
        Get progressive trust profile for risk level
        
        Args:
            risk_level: Risk level
        
        Returns:
            Trust profile with optimizations
        """
        
        profile = self.TRUST_PROFILES[risk_level]
        
        logger.info(
            f"✅ Progressive trust profile:\n"
            f"   Risk: {risk_level.value}\n"
            f"   Challenges: {profile.challenge_count}\n"
            f"   Difficulty: {profile.difficulty_level}\n"
            f"   Target: {profile.target_duration_seconds}s\n"
            f"   Fast path: {profile.enable_fast_path}"
        )
        
        return profile
    
    async def track_performance(
        self,
        session_id: str,
        event: str,
        timestamp: Optional[datetime] = None
    ) -> PerformanceMetrics:
        """
        Track performance event
        
        Args:
            session_id: Session identifier
            event: Event name
            timestamp: Event timestamp
        
        Returns:
            Updated performance metrics
        """
        
        if timestamp is None:
            timestamp = datetime.utcnow()
        
        # Get or create metrics
        async with self.postgres.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM performance_metrics WHERE session_id = $1",
                session_id
            )
            
            if not row:
                # Create new metrics
                await conn.execute(
                    """
                    INSERT INTO performance_metrics (
                        session_id, session_start
                    ) VALUES ($1, $2)
                    """,
                    session_id,
                    timestamp
                )
                
                metrics = PerformanceMetrics(
                    session_id=session_id,
                    session_start=timestamp
                )
            else:
                metrics = self._row_to_metrics(row)
            
            # Update event timestamp
            event_column = f"{event}_timestamp"
            
            await conn.execute(
                f"""
                UPDATE performance_metrics
                SET {event_column} = $2
                WHERE session_id = $1
                """,
                session_id,
                timestamp
            )
        
        # Recalculate durations
        async with self.postgres.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM performance_metrics WHERE session_id = $1",
                session_id
            )
            
            metrics = self._row_to_metrics(row)
            metrics.calculate_durations()
        
        return metrics
    
    async def get_performance_stats(
        self,
        time_window_hours: int = 24
    ) -> Dict[str, Any]:
        """
        Get performance statistics
        
        ACCEPTANCE CRITERIA: <=20 seconds median
        
        Args:
            time_window_hours: Time window for stats
        
        Returns:
            Performance statistics
        """
        
        cutoff = datetime.utcnow() - timedelta(hours=time_window_hours)
        
        async with self.postgres.acquire() as conn:
            # Get all successful completions
            rows = await conn.fetch(
                """
                SELECT total_duration_ms
                FROM performance_metrics
                WHERE session_start >= $1
                AND success = TRUE
                AND total_duration_ms IS NOT NULL
                """,
                cutoff
            )
        
        if not rows:
            return {
                "total_sessions": 0,
                "median_ms": None,
                "mean_ms": None,
                "p95_ms": None,
                "target_met": False
            }
        
        durations = [row["total_duration_ms"] for row in rows]
        
        median_ms = statistics.median(durations)
        mean_ms = statistics.mean(durations)
        p95_ms = sorted(durations)[int(len(durations) * 0.95)]
        
        # Target: 20 seconds = 20,000 ms
        target_met = median_ms <= 20000
        
        stats = {
            "total_sessions": len(durations),
            "median_ms": median_ms,
            "median_seconds": median_ms / 1000,
            "mean_ms": mean_ms,
            "mean_seconds": mean_ms / 1000,
            "p95_ms": p95_ms,
            "p95_seconds": p95_ms / 1000,
            "target_met": target_met,
            "target_ms": 20000,
            "time_window_hours": time_window_hours
        }
        
        logger.info(
            f"📊 Performance Statistics:\n"
            f"   Sessions: {stats['total_sessions']}\n"
            f"   Median: {stats['median_seconds']:.1f}s\n"
            f"   Mean: {stats['mean_seconds']:.1f}s\n"
            f"   P95: {stats['p95_seconds']:.1f}s\n"
            f"   Target met: {'✅ YES' if target_met else '❌ NO'}"
        )
        
        return stats
    
    def _row_to_metrics(self, row: Dict[str, Any]) -> PerformanceMetrics:
        """Convert database row to PerformanceMetrics"""
        
        return PerformanceMetrics(
            session_id=row["session_id"],
            session_start=row["session_start"],
            consent_shown=row.get("consent_shown_timestamp"),
            consent_granted=row.get("consent_granted_timestamp"),
            challenge_issued=row.get("challenge_issued_timestamp"),
            video_upload_start=row.get("video_upload_start_timestamp"),
            video_upload_complete=row.get("video_upload_complete_timestamp"),
            processing_start=row.get("processing_start_timestamp"),
            processing_complete=row.get("processing_complete_timestamp"),
            result_returned=row.get("result_returned_timestamp"),
            success=row.get("success", False),
            abandonment=row.get("abandonment", False),
            error_occurred=row.get("error_occurred", False)
        )