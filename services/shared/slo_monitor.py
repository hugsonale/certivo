"""
SLO Monitoring System
Track and validate Service Level Objectives
"""

import asyncpg
import redis.asyncio as redis
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
from dataclasses import dataclass
from enum import Enum
import time
import logging
import statistics

logger = logging.getLogger(__name__)


class SLOMetric(str, Enum):
    """SLO metric types"""
    API_AVAILABILITY = "api_availability"
    CHALLENGE_ISSUANCE_LATENCY = "challenge_issuance_latency"
    VERIFY_ACCEPT_LATENCY = "verify_accept_latency"
    QUEUE_PROCESSING_DELAY = "queue_processing_delay"


class SLOStatus(str, Enum):
    """SLO compliance status"""
    HEALTHY = "healthy"           # Meeting SLO
    AT_RISK = "at_risk"          # Close to SLO breach
    BREACHED = "breached"         # SLO violated
    DEGRADED = "degraded"         # Temporary degradation


@dataclass
class SLOTarget:
    """SLO target definition"""
    metric: SLOMetric
    name: str
    target_value: float
    percentile: Optional[int] = None  # For latency metrics (e.g., 95)
    unit: str = "ms"
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "metric": self.metric.value,
            "name": self.name,
            "target_value": self.target_value,
            "percentile": self.percentile,
            "unit": self.unit
        }


@dataclass
class SLOReport:
    """SLO compliance report"""
    metric: SLOMetric
    time_window: str
    target_value: float
    actual_value: float
    compliance_percentage: float
    status: SLOStatus
    samples: int
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "metric": self.metric.value,
            "time_window": self.time_window,
            "target_value": self.target_value,
            "actual_value": round(self.actual_value, 3),
            "compliance_percentage": round(self.compliance_percentage, 2),
            "status": self.status.value,
            "samples": self.samples
        }


class SLOMonitor:
    """
    SLO monitoring and validation system
    
    SLO Targets:
    - API Availability: 99.9% monthly
    - P95 Challenge Issuance: <= 300ms
    - P95 Verify Accept: <= 2500ms (excluding upload)
    - P95 Queue Processing: <= 5000ms under normal load
    """
    
    # SLO Definitions
    SLO_TARGETS = {
        SLOMetric.API_AVAILABILITY: SLOTarget(
            metric=SLOMetric.API_AVAILABILITY,
            name="API Availability",
            target_value=99.9,
            unit="%"
        ),
        SLOMetric.CHALLENGE_ISSUANCE_LATENCY: SLOTarget(
            metric=SLOMetric.CHALLENGE_ISSUANCE_LATENCY,
            name="Challenge Issuance Latency",
            target_value=300.0,
            percentile=95,
            unit="ms"
        ),
        SLOMetric.VERIFY_ACCEPT_LATENCY: SLOTarget(
            metric=SLOMetric.VERIFY_ACCEPT_LATENCY,
            name="Verify Accept Latency",
            target_value=2500.0,
            percentile=95,
            unit="ms"
        ),
        SLOMetric.QUEUE_PROCESSING_DELAY: SLOTarget(
            metric=SLOMetric.QUEUE_PROCESSING_DELAY,
            name="Queue Processing Delay",
            target_value=5000.0,
            percentile=95,
            unit="ms"
        )
    }
    
    def __init__(
        self,
        postgres_pool: asyncpg.Pool,
        redis_client: redis.Redis
    ):
        self.postgres = postgres_pool
        self.redis = redis_client
    
    async def record_request(
        self,
        endpoint: str,
        status_code: int,
        duration_ms: float,
        timestamp: Optional[datetime] = None
    ):
        """
        Record API request for availability tracking
        
        Args:
            endpoint: API endpoint
            status_code: HTTP status code
            duration_ms: Request duration in milliseconds
            timestamp: Request timestamp (defaults to now)
        """
        
        if timestamp is None:
            timestamp = datetime.utcnow()
        
        success = 200 <= status_code < 500  # 5xx errors count as unavailable
        
        # Store in Postgres
        async with self.postgres.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO api_requests
                (endpoint, status_code, duration_ms, success, timestamp)
                VALUES ($1, $2, $3, $4, $5)
                """,
                endpoint,
                status_code,
                duration_ms,
                success,
                timestamp
            )
        
        # Update Redis counters (for real-time metrics)
        date_key = timestamp.strftime("%Y-%m-%d")
        
        await self.redis.incr(f"requests:{date_key}")
        if success:
            await self.redis.incr(f"requests:success:{date_key}")
        
        # Expire after 35 days
        await self.redis.expire(f"requests:{date_key}", 35 * 86400)
        await self.redis.expire(f"requests:success:{date_key}", 35 * 86400)
    
    async def record_challenge_issuance(
        self,
        challenge_id: str,
        duration_ms: float,
        success: bool = True
    ):
        """
        Record challenge issuance latency
        
        Args:
            challenge_id: Challenge identifier
            duration_ms: Issuance duration in milliseconds
            success: Whether issuance succeeded
        """
        
        timestamp = datetime.utcnow()
        
        # Store in Postgres
        async with self.postgres.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO challenge_issuance_metrics
                (challenge_id, duration_ms, success, timestamp)
                VALUES ($1, $2, $3, $4)
                """,
                challenge_id,
                duration_ms,
                success,
                timestamp
            )
        
        # Store in Redis for P95 calculation
        await self.redis.lpush(
            "latency:challenge_issuance",
            str(duration_ms)
        )
        
        # Keep last 10,000 samples
        await self.redis.ltrim("latency:challenge_issuance", 0, 9999)
    
    async def record_verify_accept(
        self,
        session_id: str,
        duration_ms: float,
        upload_duration_ms: float,
        processing_duration_ms: float,
        success: bool = True
    ):
        """
        Record verification accept latency
        
        Args:
            session_id: Session identifier
            duration_ms: Total duration (including upload)
            upload_duration_ms: Upload transfer time
            processing_duration_ms: Server processing time (excluding upload)
            success: Whether verification succeeded
        """
        
        timestamp = datetime.utcnow()
        
        # Store in Postgres
        async with self.postgres.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO verify_accept_metrics
                (session_id, duration_ms, upload_duration_ms, 
                 processing_duration_ms, success, timestamp)
                VALUES ($1, $2, $3, $4, $5, $6)
                """,
                session_id,
                duration_ms,
                upload_duration_ms,
                processing_duration_ms,
                success,
                timestamp
            )
        
        # Store processing time (excluding upload) in Redis
        await self.redis.lpush(
            "latency:verify_accept",
            str(processing_duration_ms)
        )
        
        await self.redis.ltrim("latency:verify_accept", 0, 9999)
    
    async def record_queue_processing(
        self,
        job_id: str,
        queued_at: datetime,
        started_at: datetime,
        completed_at: datetime,
        queue_name: str
    ):
        """
        Record queue processing delay
        
        Args:
            job_id: Job identifier
            queued_at: When job was queued
            started_at: When processing started
            completed_at: When processing completed
            queue_name: Queue name
        """
        
        # Calculate delay (time from queue to start)
        delay_ms = (started_at - queued_at).total_seconds() * 1000
        
        # Calculate processing time
        processing_ms = (completed_at - started_at).total_seconds() * 1000
        
        # Store in Postgres
        async with self.postgres.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO queue_processing_metrics
                (job_id, queue_name, queued_at, started_at, completed_at,
                 delay_ms, processing_ms)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                """,
                job_id,
                queue_name,
                queued_at,
                started_at,
                completed_at,
                delay_ms,
                processing_ms
            )
        
        # Store delay in Redis
        await self.redis.lpush(
            f"latency:queue_processing:{queue_name}",
            str(delay_ms)
        )
        
        await self.redis.ltrim(f"latency:queue_processing:{queue_name}", 0, 9999)
    
    async def calculate_api_availability(
        self,
        days: int = 30
    ) -> SLOReport:
        """
        Calculate API availability SLO
        
        Args:
            days: Time window in days
        
        Returns:
            SLO report
        """
        
        since = datetime.utcnow() - timedelta(days=days)
        
        async with self.postgres.acquire() as conn:
            result = await conn.fetchrow(
                """
                SELECT 
                    COUNT(*) as total_requests,
                    COUNT(*) FILTER (WHERE success = true) as successful_requests
                FROM api_requests
                WHERE timestamp >= $1
                """,
                since
            )
        
        total = result["total_requests"]
        successful = result["successful_requests"]
        
        if total == 0:
            availability = 100.0
        else:
            availability = (successful / total) * 100
        
        target = self.SLO_TARGETS[SLOMetric.API_AVAILABILITY]
        
        # Determine status
        if availability >= target.target_value:
            status = SLOStatus.HEALTHY
        elif availability >= target.target_value - 0.05:  # Within 0.05%
            status = SLOStatus.AT_RISK
        else:
            status = SLOStatus.BREACHED
        
        compliance = (availability / target.target_value) * 100
        
        return SLOReport(
            metric=SLOMetric.API_AVAILABILITY,
            time_window=f"{days} days",
            target_value=target.target_value,
            actual_value=availability,
            compliance_percentage=compliance,
            status=status,
            samples=total
        )
    
    async def calculate_challenge_issuance_latency(
        self,
        hours: int = 24
    ) -> SLOReport:
        """
        Calculate P95 challenge issuance latency
        
        Args:
            hours: Time window in hours
        
        Returns:
            SLO report
        """
        
        since = datetime.utcnow() - timedelta(hours=hours)
        
        # Get recent samples from Postgres
        async with self.postgres.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT duration_ms
                FROM challenge_issuance_metrics
                WHERE timestamp >= $1 AND success = true
                ORDER BY timestamp DESC
                LIMIT 10000
                """,
                since
            )
        
        if not rows:
            return self._empty_report(SLOMetric.CHALLENGE_ISSUANCE_LATENCY, hours)
        
        latencies = [row["duration_ms"] for row in rows]
        p95 = statistics.quantiles(latencies, n=100)[94]  # 95th percentile
        
        target = self.SLO_TARGETS[SLOMetric.CHALLENGE_ISSUANCE_LATENCY]
        
        # Determine status
        if p95 <= target.target_value:
            status = SLOStatus.HEALTHY
        elif p95 <= target.target_value * 1.1:  # Within 10%
            status = SLOStatus.AT_RISK
        else:
            status = SLOStatus.BREACHED
        
        compliance = (target.target_value / max(p95, target.target_value)) * 100
        
        return SLOReport(
            metric=SLOMetric.CHALLENGE_ISSUANCE_LATENCY,
            time_window=f"{hours} hours",
            target_value=target.target_value,
            actual_value=p95,
            compliance_percentage=compliance,
            status=status,
            samples=len(latencies)
        )
    
    async def calculate_verify_accept_latency(
        self,
        hours: int = 24
    ) -> SLOReport:
        """
        Calculate P95 verify accept latency (excluding upload)
        
        Args:
            hours: Time window in hours
        
        Returns:
            SLO report
        """
        
        since = datetime.utcnow() - timedelta(hours=hours)
        
        # Get processing times (excluding upload)
        async with self.postgres.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT processing_duration_ms
                FROM verify_accept_metrics
                WHERE timestamp >= $1 AND success = true
                ORDER BY timestamp DESC
                LIMIT 10000
                """,
                since
            )
        
        if not rows:
            return self._empty_report(SLOMetric.VERIFY_ACCEPT_LATENCY, hours)
        
        latencies = [row["processing_duration_ms"] for row in rows]
        p95 = statistics.quantiles(latencies, n=100)[94]
        
        target = self.SLO_TARGETS[SLOMetric.VERIFY_ACCEPT_LATENCY]
        
        # Determine status
        if p95 <= target.target_value:
            status = SLOStatus.HEALTHY
        elif p95 <= target.target_value * 1.1:
            status = SLOStatus.AT_RISK
        else:
            status = SLOStatus.BREACHED
        
        compliance = (target.target_value / max(p95, target.target_value)) * 100
        
        return SLOReport(
            metric=SLOMetric.VERIFY_ACCEPT_LATENCY,
            time_window=f"{hours} hours",
            target_value=target.target_value,
            actual_value=p95,
            compliance_percentage=compliance,
            status=status,
            samples=len(latencies)
        )
    
    async def calculate_queue_processing_delay(
        self,
        queue_name: str = "verification",
        hours: int = 24
    ) -> SLOReport:
        """
        Calculate P95 queue processing delay
        
        Args:
            queue_name: Queue to analyze
            hours: Time window in hours
        
        Returns:
            SLO report
        """
        
        since = datetime.utcnow() - timedelta(hours=hours)
        
        async with self.postgres.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT delay_ms
                FROM queue_processing_metrics
                WHERE queued_at >= $1 AND queue_name = $2
                ORDER BY queued_at DESC
                LIMIT 10000
                """,
                since,
                queue_name
            )
        
        if not rows:
            return self._empty_report(SLOMetric.QUEUE_PROCESSING_DELAY, hours)
        
        delays = [row["delay_ms"] for row in rows]
        p95 = statistics.quantiles(delays, n=100)[94]
        
        target = self.SLO_TARGETS[SLOMetric.QUEUE_PROCESSING_DELAY]
        
        # Determine status
        if p95 <= target.target_value:
            status = SLOStatus.HEALTHY
        elif p95 <= target.target_value * 1.1:
            status = SLOStatus.AT_RISK
        else:
            status = SLOStatus.BREACHED
        
        compliance = (target.target_value / max(p95, target.target_value)) * 100
        
        return SLOReport(
            metric=SLOMetric.QUEUE_PROCESSING_DELAY,
            time_window=f"{hours} hours",
            target_value=target.target_value,
            actual_value=p95,
            compliance_percentage=compliance,
            status=status,
            samples=len(delays)
        )
    
    def _empty_report(
        self,
        metric: SLOMetric,
        hours: int
    ) -> SLOReport:
        """Generate empty report when no data available"""
        
        target = self.SLO_TARGETS[metric]
        
        return SLOReport(
            metric=metric,
            time_window=f"{hours} hours",
            target_value=target.target_value,
            actual_value=0.0,
            compliance_percentage=100.0,
            status=SLOStatus.HEALTHY,
            samples=0
        )
    
    async def generate_slo_dashboard(self) -> Dict[str, Any]:
        """
        Generate comprehensive SLO dashboard
        
        Returns:
            SLO status for all metrics
        """
        
        # Calculate all SLOs
        availability = await self.calculate_api_availability(days=30)
        challenge_latency = await self.calculate_challenge_issuance_latency(hours=24)
        verify_latency = await self.calculate_verify_accept_latency(hours=24)
        queue_delay = await self.calculate_queue_processing_delay(hours=24)
        
        # Determine overall health
        reports = [availability, challenge_latency, verify_latency, queue_delay]
        
        breached_count = sum(1 for r in reports if r.status == SLOStatus.BREACHED)
        at_risk_count = sum(1 for r in reports if r.status == SLOStatus.AT_RISK)
        
        if breached_count > 0:
            overall_status = "DEGRADED"
        elif at_risk_count > 0:
            overall_status = "AT_RISK"
        else:
            overall_status = "HEALTHY"
        
        dashboard = {
            "generated_at": datetime.utcnow().isoformat(),
            "overall_status": overall_status,
            "slo_reports": {
                "api_availability": availability.to_dict(),
                "challenge_issuance_latency": challenge_latency.to_dict(),
                "verify_accept_latency": verify_latency.to_dict(),
                "queue_processing_delay": queue_delay.to_dict()
            },
            "summary": {
                "total_slos": len(reports),
                "healthy": sum(1 for r in reports if r.status == SLOStatus.HEALTHY),
                "at_risk": at_risk_count,
                "breached": breached_count
            }
        }
        
        logger.info(
            f"📊 SLO Dashboard Generated:\n"
            f"   Overall Status: {overall_status}\n"
            f"   API Availability: {availability.actual_value:.3f}% (target: {availability.target_value}%)\n"
            f"   Challenge P95: {challenge_latency.actual_value:.1f}ms (target: {challenge_latency.target_value}ms)\n"
            f"   Verify P95: {verify_latency.actual_value:.1f}ms (target: {verify_latency.target_value}ms)\n"
            f"   Queue P95: {queue_delay.actual_value:.1f}ms (target: {queue_delay.target_value}ms)"
        )
        
        return dashboard