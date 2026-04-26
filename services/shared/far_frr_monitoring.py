"""
False Acceptance Rate (FAR) and False Rejection Rate (FRR) Monitoring
Tracks and reports biometric system performance metrics
"""

import redis.asyncio as redis
import asyncpg
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timedelta
import json


class FARFRRMonitor:
    """
    Monitor and track FAR/FRR metrics
    
    Definitions:
    - FAR (False Acceptance Rate): Impostor accepted as genuine
    - FRR (False Rejection Rate): Genuine user rejected
    - EER (Equal Error Rate): Point where FAR = FRR
    """
    
    def __init__(
        self,
        redis_client: redis.Redis,
        postgres_pool: asyncpg.Pool
    ):
        self.redis = redis_client
        self.postgres = postgres_pool
        
        # Policy thresholds
        self.far_threshold = 0.01  # 1% max FAR
        self.frr_threshold = 0.05  # 5% max FRR
        self.target_eer = 0.03     # 3% target EER
    
    async def record_verification_outcome(
        self,
        session_id: str,
        device_id: str,
        is_genuine: bool,
        was_accepted: bool,
        liveness_score: float,
        metadata: Dict[str, Any]
    ):
        """
        Record verification outcome for FAR/FRR calculation
        
        Args:
            session_id: Verification session ID
            device_id: Device identifier
            is_genuine: True if genuine user (ground truth)
            was_accepted: True if system accepted verification
            liveness_score: Liveness detection score (0-1)
            metadata: Additional context
        """
        
        # Classify outcome
        outcome_type = self._classify_outcome(is_genuine, was_accepted)
        
        # Store in Postgres
        async with self.postgres.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO verification_outcomes
                (session_id, device_id, is_genuine, was_accepted, 
                 outcome_type, liveness_score, metadata, timestamp_utc)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                """,
                session_id,
                device_id,
                is_genuine,
                was_accepted,
                outcome_type,
                liveness_score,
                json.dumps(metadata),
                datetime.utcnow()
            )
        
        # Update Redis counters
        date_key = datetime.utcnow().strftime("%Y-%m-%d")
        
        await self.redis.hincrby(f"verification_outcomes:{date_key}", outcome_type, 1)
        await self.redis.expire(f"verification_outcomes:{date_key}", 86400 * 30)  # 30 days
    
    def _classify_outcome(self, is_genuine: bool, was_accepted: bool) -> str:
        """
        Classify verification outcome
        
        Returns:
            - "true_accept": Genuine user accepted (Correct)
            - "false_reject": Genuine user rejected (Type I error - FRR)
            - "false_accept": Impostor accepted (Type II error - FAR)
            - "true_reject": Impostor rejected (Correct)
        """
        
        if is_genuine and was_accepted:
            return "true_accept"
        elif is_genuine and not was_accepted:
            return "false_reject"  # Contributes to FRR
        elif not is_genuine and was_accepted:
            return "false_accept"  # Contributes to FAR
        else:
            return "true_reject"
    
    async def calculate_far_frr(
        self,
        time_window_hours: int = 24
    ) -> Dict[str, Any]:
        """
        Calculate FAR and FRR for specified time window
        
        Returns:
            FAR, FRR, EER, and detailed metrics
        """
        
        start_time = datetime.utcnow() - timedelta(hours=time_window_hours)
        
        # Query verification outcomes
        async with self.postgres.acquire() as conn:
            outcomes = await conn.fetch(
                """
                SELECT outcome_type, COUNT(*) as count
                FROM verification_outcomes
                WHERE timestamp_utc >= $1
                GROUP BY outcome_type
                """,
                start_time
            )
        
        # Convert to dict
        outcome_counts = {row['outcome_type']: row['count'] for row in outcomes}
        
        # Extract counts
        true_accept = outcome_counts.get("true_accept", 0)
        false_reject = outcome_counts.get("false_reject", 0)
        false_accept = outcome_counts.get("false_accept", 0)
        true_reject = outcome_counts.get("true_reject", 0)
        
        # Calculate FAR and FRR
        total_genuine = true_accept + false_reject
        total_impostor = false_accept + true_reject
        
        far = (false_accept / total_impostor) if total_impostor > 0 else 0.0
        frr = (false_reject / total_genuine) if total_genuine > 0 else 0.0
        
        # Calculate accuracy
        total = true_accept + false_reject + false_accept + true_reject
        accuracy = ((true_accept + true_reject) / total) if total > 0 else 0.0
        
        # Estimate EER (simplified - actual EER requires ROC curve)
        eer = (far + frr) / 2.0
        
        return {
            "far": far,
            "frr": frr,
            "eer": eer,
            "accuracy": accuracy,
            "counts": {
                "true_accept": true_accept,
                "false_reject": false_reject,
                "false_accept": false_accept,
                "true_reject": true_reject,
                "total_genuine": total_genuine,
                "total_impostor": total_impostor,
                "total": total
            },
            "time_window_hours": time_window_hours,
            "within_policy": far <= self.far_threshold and frr <= self.frr_threshold
        }
    
    async def calculate_roc_curve(
        self,
        time_window_hours: int = 24,
        num_thresholds: int = 20
    ) -> Dict[str, Any]:
        """
        Calculate ROC curve data for threshold tuning
        
        Returns:
            FAR/FRR pairs at different thresholds
        """
        
        start_time = datetime.utcnow() - timedelta(hours=time_window_hours)
        
        # Get all outcomes with liveness scores
        async with self.postgres.acquire() as conn:
            outcomes = await conn.fetch(
                """
                SELECT is_genuine, liveness_score
                FROM verification_outcomes
                WHERE timestamp_utc >= $1
                ORDER BY liveness_score
                """,
                start_time
            )
        
        if not outcomes:
            return {
                "roc_points": [],
                "optimal_threshold": 0.7,
                "eer": 0.0
            }
        
        # Extract scores and labels
        genuine_scores = [row['liveness_score'] for row in outcomes if row['is_genuine']]
        impostor_scores = [row['liveness_score'] for row in outcomes if not row['is_genuine']]
        
        # Calculate FAR/FRR at different thresholds
        thresholds = [i / num_thresholds for i in range(num_thresholds + 1)]
        roc_points = []
        
        min_eer = float('inf')
        optimal_threshold = 0.5
        
        for threshold in thresholds:
            # FRR: Genuine users below threshold
            false_rejects = sum(1 for score in genuine_scores if score < threshold)
            frr = false_rejects / len(genuine_scores) if genuine_scores else 0.0
            
            # FAR: Impostors above threshold
            false_accepts = sum(1 for score in impostor_scores if score >= threshold)
            far = false_accepts / len(impostor_scores) if impostor_scores else 0.0
            
            roc_points.append({
                "threshold": threshold,
                "far": far,
                "frr": frr
            })
            
            # Track EER
            eer = abs(far - frr)
            if eer < min_eer:
                min_eer = eer
                optimal_threshold = threshold
        
        return {
            "roc_points": roc_points,
            "optimal_threshold": optimal_threshold,
            "eer": min_eer,
            "num_genuine": len(genuine_scores),
            "num_impostor": len(impostor_scores)
        }
    
    async def get_performance_trend(
        self,
        days: int = 7
    ) -> Dict[str, Any]:
        """
        Get performance trend over time
        
        Returns:
            Daily FAR/FRR metrics
        """
        
        trends = []
        
        for day_offset in range(days):
            date = datetime.utcnow() - timedelta(days=day_offset)
            start = date.replace(hour=0, minute=0, second=0, microsecond=0)
            end = start + timedelta(days=1)
            
            # Get outcomes for this day
            async with self.postgres.acquire() as conn:
                outcomes = await conn.fetch(
                    """
                    SELECT outcome_type, COUNT(*) as count
                    FROM verification_outcomes
                    WHERE timestamp_utc >= $1 AND timestamp_utc < $2
                    GROUP BY outcome_type
                    """,
                    start, end
                )
            
            outcome_counts = {row['outcome_type']: row['count'] for row in outcomes}
            
            true_accept = outcome_counts.get("true_accept", 0)
            false_reject = outcome_counts.get("false_reject", 0)
            false_accept = outcome_counts.get("false_accept", 0)
            true_reject = outcome_counts.get("true_reject", 0)
            
            total_genuine = true_accept + false_reject
            total_impostor = false_accept + true_reject
            
            far = (false_accept / total_impostor) if total_impostor > 0 else 0.0
            frr = (false_reject / total_genuine) if total_genuine > 0 else 0.0
            
            trends.append({
                "date": start.strftime("%Y-%m-%d"),
                "far": far,
                "frr": frr,
                "total_verifications": true_accept + false_reject + false_accept + true_reject
            })
        
        return {
            "trends": list(reversed(trends)),
            "days": days
        }
    
    async def check_policy_compliance(self) -> Dict[str, Any]:
        """
        Check if FAR/FRR are within policy thresholds
        
        Returns:
            Compliance status and recommended actions
        """
        
        # Calculate current metrics
        metrics = await self.calculate_far_frr(time_window_hours=24)
        
        far = metrics["far"]
        frr = metrics["frr"]
        
        compliance = {
            "far_compliant": far <= self.far_threshold,
            "frr_compliant": frr <= self.frr_threshold,
            "overall_compliant": (far <= self.far_threshold and frr <= self.frr_threshold)
        }
        
        # Recommendations
        recommendations = []
        
        if far > self.far_threshold:
            recommendations.append({
                "issue": "FAR exceeds threshold",
                "current": far,
                "threshold": self.far_threshold,
                "action": "Increase liveness detection threshold or add more signals"
            })
        
        if frr > self.frr_threshold:
            recommendations.append({
                "issue": "FRR exceeds threshold",
                "current": frr,
                "threshold": self.frr_threshold,
                "action": "Lower liveness detection threshold or improve user guidance"
            })
        
        return {
            "compliance": compliance,
            "metrics": metrics,
            "recommendations": recommendations,
            "policy": {
                "far_threshold": self.far_threshold,
                "frr_threshold": self.frr_threshold,
                "target_eer": self.target_eer
            }
        }