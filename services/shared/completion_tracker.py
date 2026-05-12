"""
Challenge Completion Rate Tracker
Track and analyze legitimate user completion rates
"""

import asyncpg
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from dataclasses import dataclass
from enum import Enum
import json


class CompletionStatus(str, Enum):
    """Challenge completion status"""
    COMPLETED = "completed"
    FAILED = "failed"
    ABANDONED = "abandoned"
    TIMEOUT = "timeout"


@dataclass
class CompletionMetrics:
    """Completion metrics for a template"""
    template_id: str
    total_attempts: int
    completed: int
    failed: int
    abandoned: int
    timeout: int
    completion_rate: float
    avg_duration_seconds: float
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "template_id": self.template_id,
            "total_attempts": self.total_attempts,
            "completed": self.completed,
            "failed": self.failed,
            "abandoned": self.abandoned,
            "timeout": self.timeout,
            "completion_rate": self.completion_rate,
            "avg_duration_seconds": self.avg_duration_seconds
        }


class CompletionTracker:
    """
    Track challenge completion rates
    
    Features:
    - Per-template completion tracking
    - Cohort analysis (pilot vs general)
    - Accessibility-aware metrics
    - Real-time completion rate monitoring
    """
    
    def __init__(self, postgres_pool: asyncpg.Pool):
        self.postgres = postgres_pool
    
    async def record_attempt(
        self,
        challenge_id: str,
        template_id: str,
        user_id: str,
        status: CompletionStatus,
        duration_seconds: float,
        is_pilot_user: bool = False,
        accessibility_profile: Optional[Dict[str, Any]] = None,
        failure_reason: Optional[str] = None
    ):
        """
        Record challenge attempt
        
        Args:
            challenge_id: Challenge identifier
            template_id: Template used
            user_id: User identifier
            status: Completion status
            duration_seconds: Time taken
            is_pilot_user: Whether user is in pilot cohort
            accessibility_profile: User accessibility constraints
            failure_reason: Reason for failure (if applicable)
        """
        
        async with self.postgres.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO challenge_completion_tracking
                (challenge_id, template_id, user_id, status, duration_seconds,
                 is_pilot_user, accessibility_profile, failure_reason, attempted_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                """,
                challenge_id,
                template_id,
                user_id,
                status.value,
                duration_seconds,
                is_pilot_user,
                json.dumps(accessibility_profile) if accessibility_profile else None,
                failure_reason,
                datetime.utcnow()
            )
    
    async def get_completion_rate(
        self,
        template_id: Optional[str] = None,
        is_pilot_only: bool = False,
        days: int = 30
    ) -> float:
        """
        Get completion rate
        
        Args:
            template_id: Specific template (None for all)
            is_pilot_only: Only pilot cohort users
            days: Time window in days
        
        Returns:
            Completion rate (0.0 - 1.0)
        """
        
        since = datetime.utcnow() - timedelta(days=days)
        
        where_clauses = ["attempted_at >= $1"]
        params = [since]
        param_idx = 2
        
        if template_id:
            where_clauses.append(f"template_id = ${param_idx}")
            params.append(template_id)
            param_idx += 1
        
        if is_pilot_only:
            where_clauses.append(f"is_pilot_user = ${param_idx}")
            params.append(True)
            param_idx += 1
        
        query = f"""
            SELECT 
                COUNT(*) as total,
                COUNT(*) FILTER (WHERE status = 'completed') as completed
            FROM challenge_completion_tracking
            WHERE {' AND '.join(where_clauses)}
        """
        
        async with self.postgres.acquire() as conn:
            row = await conn.fetchrow(query, *params)
        
        if row["total"] == 0:
            return 0.0
        
        return row["completed"] / row["total"]
    
    async def get_template_metrics(
        self,
        template_id: str,
        is_pilot_only: bool = False,
        days: int = 30
    ) -> CompletionMetrics:
        """
        Get detailed metrics for template
        
        Args:
            template_id: Template identifier
            is_pilot_only: Only pilot cohort
            days: Time window
        
        Returns:
            Completion metrics
        """
        
        since = datetime.utcnow() - timedelta(days=days)
        
        where_clauses = ["attempted_at >= $1", "template_id = $2"]
        params = [since, template_id]
        
        if is_pilot_only:
            where_clauses.append("is_pilot_user = $3")
            params.append(True)
        
        query = f"""
            SELECT 
                COUNT(*) as total,
                COUNT(*) FILTER (WHERE status = 'completed') as completed,
                COUNT(*) FILTER (WHERE status = 'failed') as failed,
                COUNT(*) FILTER (WHERE status = 'abandoned') as abandoned,
                COUNT(*) FILTER (WHERE status = 'timeout') as timeout,
                AVG(duration_seconds) FILTER (WHERE status = 'completed') as avg_duration
            FROM challenge_completion_tracking
            WHERE {' AND '.join(where_clauses)}
        """
        
        async with self.postgres.acquire() as conn:
            row = await conn.fetchrow(query, *params)
        
        total = row["total"] or 0
        completed = row["completed"] or 0
        
        completion_rate = (completed / total) if total > 0 else 0.0
        
        return CompletionMetrics(
            template_id=template_id,
            total_attempts=total,
            completed=completed,
            failed=row["failed"] or 0,
            abandoned=row["abandoned"] or 0,
            timeout=row["timeout"] or 0,
            completion_rate=completion_rate,
            avg_duration_seconds=float(row["avg_duration"] or 0)
        )
    
    async def get_all_template_metrics(
        self,
        is_pilot_only: bool = False,
        days: int = 30
    ) -> List[CompletionMetrics]:
        """
        Get metrics for all templates
        
        Args:
            is_pilot_only: Only pilot cohort
            days: Time window
        
        Returns:
            List of template metrics
        """
        
        since = datetime.utcnow() - timedelta(days=days)
        
        where_clauses = ["attempted_at >= $1"]
        params = [since]
        
        if is_pilot_only:
            where_clauses.append("is_pilot_user = $2")
            params.append(True)
        
        query = f"""
            SELECT 
                template_id,
                COUNT(*) as total,
                COUNT(*) FILTER (WHERE status = 'completed') as completed,
                COUNT(*) FILTER (WHERE status = 'failed') as failed,
                COUNT(*) FILTER (WHERE status = 'abandoned') as abandoned,
                COUNT(*) FILTER (WHERE status = 'timeout') as timeout,
                AVG(duration_seconds) FILTER (WHERE status = 'completed') as avg_duration
            FROM challenge_completion_tracking
            WHERE {' AND '.join(where_clauses)}
            GROUP BY template_id
            ORDER BY template_id
        """
        
        async with self.postgres.acquire() as conn:
            rows = await conn.fetch(query, *params)
        
        metrics = []
        
        for row in rows:
            total = row["total"]
            completed = row["completed"]
            completion_rate = (completed / total) if total > 0 else 0.0
            
            metrics.append(CompletionMetrics(
                template_id=row["template_id"],
                total_attempts=total,
                completed=completed,
                failed=row["failed"],
                abandoned=row["abandoned"],
                timeout=row["timeout"],
                completion_rate=completion_rate,
                avg_duration_seconds=float(row["avg_duration"] or 0)
            ))
        
        return metrics
    
    async def get_accessibility_breakdown(
        self,
        is_pilot_only: bool = False,
        days: int = 30
    ) -> Dict[str, float]:
        """
        Get completion rates by accessibility profile
        
        Args:
            is_pilot_only: Only pilot cohort
            days: Time window
        
        Returns:
            Dict of {profile_type: completion_rate}
        """
        
        since = datetime.utcnow() - timedelta(days=days)
        
        where_clauses = ["attempted_at >= $1", "accessibility_profile IS NOT NULL"]
        params = [since]
        
        if is_pilot_only:
            where_clauses.append("is_pilot_user = $2")
            params.append(True)
        
        query = f"""
            SELECT 
                accessibility_profile,
                COUNT(*) as total,
                COUNT(*) FILTER (WHERE status = 'completed') as completed
            FROM challenge_completion_tracking
            WHERE {' AND '.join(where_clauses)}
            GROUP BY accessibility_profile
        """
        
        async with self.postgres.acquire() as conn:
            rows = await conn.fetch(query, *params)
        
        breakdown = {}
        
        for row in rows:
            profile = json.loads(row["accessibility_profile"])
            
            # Create profile key
            constraints = []
            if profile.get("limited_mobility"):
                constraints.append("limited_mobility")
            if profile.get("vision_impaired"):
                constraints.append("vision_impaired")
            if profile.get("hearing_impaired"):
                constraints.append("hearing_impaired")
            
            profile_key = "+".join(constraints) if constraints else "no_constraints"
            
            total = row["total"]
            completed = row["completed"]
            completion_rate = (completed / total) if total > 0 else 0.0
            
            breakdown[profile_key] = completion_rate
        
        return breakdown
    
    async def get_failure_reasons(
        self,
        template_id: Optional[str] = None,
        is_pilot_only: bool = False,
        days: int = 30
    ) -> Dict[str, int]:
        """
        Get distribution of failure reasons
        
        Args:
            template_id: Specific template (None for all)
            is_pilot_only: Only pilot cohort
            days: Time window
        
        Returns:
            Dict of {failure_reason: count}
        """
        
        since = datetime.utcnow() - timedelta(days=days)
        
        where_clauses = [
            "attempted_at >= $1",
            "status = 'failed'",
            "failure_reason IS NOT NULL"
        ]
        params = [since]
        param_idx = 2
        
        if template_id:
            where_clauses.append(f"template_id = ${param_idx}")
            params.append(template_id)
            param_idx += 1
        
        if is_pilot_only:
            where_clauses.append(f"is_pilot_user = ${param_idx}")
            params.append(True)
            param_idx += 1
        
        query = f"""
            SELECT failure_reason, COUNT(*) as count
            FROM challenge_completion_tracking
            WHERE {' AND '.join(where_clauses)}
            GROUP BY failure_reason
            ORDER BY count DESC
        """
        
        async with self.postgres.acquire() as conn:
            rows = await conn.fetch(query, *params)
        
        return {row["failure_reason"]: row["count"] for row in rows}
    
    async def generate_completion_report(
        self,
        is_pilot_only: bool = False,
        days: int = 30
    ) -> Dict[str, Any]:
        """
        Generate comprehensive completion report
        
        Args:
            is_pilot_only: Only pilot cohort
            days: Time window
        
        Returns:
            Comprehensive report
        """
        
        # Overall completion rate
        overall_rate = await self.get_completion_rate(
            is_pilot_only=is_pilot_only,
            days=days
        )
        
        # Per-template metrics
        template_metrics = await self.get_all_template_metrics(
            is_pilot_only=is_pilot_only,
            days=days
        )
        
        # Accessibility breakdown
        accessibility_breakdown = await self.get_accessibility_breakdown(
            is_pilot_only=is_pilot_only,
            days=days
        )
        
        # Failure reasons
        failure_reasons = await self.get_failure_reasons(
            is_pilot_only=is_pilot_only,
            days=days
        )
        
        # Total attempts
        since = datetime.utcnow() - timedelta(days=days)
        
        where_clauses = ["attempted_at >= $1"]
        params = [since]
        
        if is_pilot_only:
            where_clauses.append("is_pilot_user = $2")
            params.append(True)
        
        query = f"""
            SELECT COUNT(*) as total
            FROM challenge_completion_tracking
            WHERE {' AND '.join(where_clauses)}
        """
        
        async with self.postgres.acquire() as conn:
            row = await conn.fetchrow(query, *params)
        
        total_attempts = row["total"]
        
        report = {
            "report_generated_at": datetime.utcnow().isoformat(),
            "cohort": "pilot" if is_pilot_only else "all",
            "time_window_days": days,
            "total_attempts": total_attempts,
            "overall_completion_rate": overall_rate,
            "acceptance_criteria_met": overall_rate >= 0.85,
            "template_metrics": [m.to_dict() for m in template_metrics],
            "accessibility_breakdown": accessibility_breakdown,
            "failure_reasons": failure_reasons,
            "summary": {
                "templates_above_85_percent": sum(
                    1 for m in template_metrics if m.completion_rate >= 0.85
                ),
                "templates_below_85_percent": sum(
                    1 for m in template_metrics if m.completion_rate < 0.85
                ),
                "best_template": max(
                    template_metrics,
                    key=lambda m: m.completion_rate
                ).template_id if template_metrics else None,
                "worst_template": min(
                    template_metrics,
                    key=lambda m: m.completion_rate
                ).template_id if template_metrics else None
            }
        }
        
        return report