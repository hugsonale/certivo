"""
SLO Monitoring Tests

Acceptance Criteria:
1. API availability: 99.9% monthly
2. P95 challenge issuance: <= 300ms
3. P95 verify accept: <= 2500ms (excluding upload)
4. P95 queue processing: <= 5000ms
"""

import pytest
import asyncio
import asyncpg
import redis.asyncio as redis
from datetime import datetime, timedelta
import random
import sys
import os

sys.path.insert(0, 'services/shared')

from slo_monitor import SLOMonitor, SLOMetric, SLOStatus


class TestSLOMonitoring:
    """Test SLO monitoring system"""
    
    @pytest.fixture
    async def monitor(self):
        """Setup SLO monitor"""
        
        postgres_pool = await asyncpg.create_pool(
            "postgresql://certivo:certivo@localhost:5432/certivo"
        )
        
        redis_client = await redis.from_url("redis://localhost:6379")
        
        monitor = SLOMonitor(postgres_pool, redis_client)
        
        yield monitor
        
        await postgres_pool.close()
        await redis_client.close()
    
    @pytest.mark.asyncio
    async def test_record_api_request(self, monitor):
        """Test API request recording"""
        
        await monitor.record_request(
            endpoint="/api/v1/challenges",
            status_code=200,
            duration_ms=150.5
        )
        
        # Verify stored in database
        async with monitor.postgres.acquire() as conn:
            count = await conn.fetchval(
                """
                SELECT COUNT(*) FROM api_requests
                WHERE endpoint = '/api/v1/challenges'
                AND status_code = 200
                """
            )
        
        assert count >= 1
        
        print("✅ API request recording validated")
    
    @pytest.mark.asyncio
    async def test_api_availability_calculation(self, monitor):
        """
        ACCEPTANCE CRITERIA 1: API Availability 99.9%
        
        Simulate requests and verify calculation
        """
        
        print("\n" + "="*60)
        print("ACCEPTANCE TEST: API Availability >= 99.9%")
        print("="*60)
        
        # Simulate 10,000 requests
        print(f"\n✓ Simulating 10,000 API requests...")
        
        successful_requests = 9995  # 99.95% success rate
        failed_requests = 5
        
        # Record successful requests
        for i in range(successful_requests):
            await monitor.record_request(
                endpoint="/api/v1/test",
                status_code=200,
                duration_ms=random.uniform(50, 200)
            )
        
        # Record failed requests (5xx errors)
        for i in range(failed_requests):
            await monitor.record_request(
                endpoint="/api/v1/test",
                status_code=500,
                duration_ms=random.uniform(100, 300)
            )
        
        print(f"  Successful: {successful_requests}")
        print(f"  Failed (5xx): {failed_requests}")
        
        # Calculate availability
        report = await monitor.calculate_api_availability(days=1)
        
        print(f"\n✓ API Availability Report:")
        print(f"  Target: {report.target_value}%")
        print(f"  Actual: {report.actual_value:.3f}%")
        print(f"  Status: {report.status.value}")
        print(f"  Compliance: {report.compliance_percentage:.2f}%")
        
        # Verify SLO met
        assert report.actual_value >= 99.9, \
            f"API availability {report.actual_value:.3f}% below 99.9% target"
        
        assert report.status == SLOStatus.HEALTHY
        
        print("\n" + "="*60)
        print(f"✅ ACCEPTANCE CRITERIA MET: API Availability {report.actual_value:.3f}%")
        print("="*60)
    
    @pytest.mark.asyncio
    async def test_challenge_issuance_latency(self, monitor):
        """
        ACCEPTANCE CRITERIA 2: P95 Challenge Issuance <= 300ms
        
        Simulate challenge issuance and verify P95
        """
        
        print("\n" + "="*60)
        print("ACCEPTANCE TEST: P95 Challenge Issuance <= 300ms")
        print("="*60)
        
        # Simulate 1,000 challenge issuances
        print(f"\n✓ Simulating 1,000 challenge issuances...")
        
        latencies = []
        
        for i in range(1000):
            # Most requests fast (50-200ms), some slower (200-280ms)
            if i < 950:
                latency = random.uniform(50, 200)
            else:
                latency = random.uniform(200, 280)
            
            latencies.append(latency)
            
            await monitor.record_challenge_issuance(
                challenge_id=f"CH-TEST-{i:04d}",
                duration_ms=latency,
                success=True
            )
        
        # Calculate actual P95
        latencies_sorted = sorted(latencies)
        actual_p95 = latencies_sorted[int(len(latencies) * 0.95)]
        
        print(f"  Simulated P95: {actual_p95:.1f}ms")
        
        # Calculate SLO report
        report = await monitor.calculate_challenge_issuance_latency(hours=1)
        
        print(f"\n✓ Challenge Issuance Latency Report:")
        print(f"  Target (P95): {report.target_value}ms")
        print(f"  Actual (P95): {report.actual_value:.1f}ms")
        print(f"  Status: {report.status.value}")
        print(f"  Samples: {report.samples}")
        
        # Verify SLO met
        assert report.actual_value <= 300, \
            f"P95 latency {report.actual_value:.1f}ms exceeds 300ms target"
        
        assert report.status == SLOStatus.HEALTHY
        
        print("\n" + "="*60)
        print(f"✅ ACCEPTANCE CRITERIA MET: P95 Challenge Issuance {report.actual_value:.1f}ms")
        print("="*60)
    
    @pytest.mark.asyncio
    async def test_verify_accept_latency(self, monitor):
        """
        ACCEPTANCE CRITERIA 3: P95 Verify Accept <= 2500ms (excluding upload)
        
        Simulate verification and verify P95
        """
        
        print("\n" + "="*60)
        print("ACCEPTANCE TEST: P95 Verify Accept <= 2500ms")
        print("="*60)
        
        # Simulate 1,000 verifications
        print(f"\n✓ Simulating 1,000 verifications...")
        
        processing_latencies = []
        
        for i in range(1000):
            # Upload time (not counted): 500-2000ms
            upload_time = random.uniform(500, 2000)
            
            # Processing time (counted): most 800-1800ms, some up to 2400ms
            if i < 950:
                processing_time = random.uniform(800, 1800)
            else:
                processing_time = random.uniform(1800, 2400)
            
            processing_latencies.append(processing_time)
            
            total_time = upload_time + processing_time
            
            await monitor.record_verify_accept(
                session_id=f"SES-TEST-{i:04d}",
                duration_ms=total_time,
                upload_duration_ms=upload_time,
                processing_duration_ms=processing_time,
                success=True
            )
        
        # Calculate actual P95
        processing_sorted = sorted(processing_latencies)
        actual_p95 = processing_sorted[int(len(processing_latencies) * 0.95)]
        
        print(f"  Simulated P95 (processing only): {actual_p95:.1f}ms")
        
        # Calculate SLO report
        report = await monitor.calculate_verify_accept_latency(hours=1)
        
        print(f"\n✓ Verify Accept Latency Report:")
        print(f"  Target (P95): {report.target_value}ms")
        print(f"  Actual (P95): {report.actual_value:.1f}ms")
        print(f"  Status: {report.status.value}")
        print(f"  Samples: {report.samples}")
        print(f"  Note: Excluding upload transfer time")
        
        # Verify SLO met
        assert report.actual_value <= 2500, \
            f"P95 latency {report.actual_value:.1f}ms exceeds 2500ms target"
        
        assert report.status == SLOStatus.HEALTHY
        
        print("\n" + "="*60)
        print(f"✅ ACCEPTANCE CRITERIA MET: P95 Verify Accept {report.actual_value:.1f}ms")
        print("="*60)
    
    @pytest.mark.asyncio
    async def test_queue_processing_delay(self, monitor):
        """
        ACCEPTANCE CRITERIA 4: P95 Queue Processing <= 5000ms
        
        Simulate queue processing and verify P95
        """
        
        print("\n" + "="*60)
        print("ACCEPTANCE TEST: P95 Queue Processing <= 5000ms")
        print("="*60)
        
        # Simulate 1,000 queue jobs
        print(f"\n✓ Simulating 1,000 queue jobs...")
        
        delays = []
        
        for i in range(1000):
            # Most jobs process quickly (100-1000ms delay)
            # Some have higher delay (1000-4500ms)
            if i < 950:
                delay_seconds = random.uniform(0.1, 1.0)
            else:
                delay_seconds = random.uniform(1.0, 4.5)
            
            delays.append(delay_seconds * 1000)
            
            now = datetime.utcnow()
            queued_at = now - timedelta(seconds=delay_seconds + 2)
            started_at = now - timedelta(seconds=2)
            completed_at = now
            
            await monitor.record_queue_processing(
                job_id=f"JOB-TEST-{i:04d}",
                queued_at=queued_at,
                started_at=started_at,
                completed_at=completed_at,
                queue_name="verification"
            )
        
        # Calculate actual P95
        delays_sorted = sorted(delays)
        actual_p95 = delays_sorted[int(len(delays) * 0.95)]
        
        print(f"  Simulated P95: {actual_p95:.1f}ms")
        
        # Calculate SLO report
        report = await monitor.calculate_queue_processing_delay(
            queue_name="verification",
            hours=1
        )
        
        print(f"\n✓ Queue Processing Delay Report:")
        print(f"  Target (P95): {report.target_value}ms")
        print(f"  Actual (P95): {report.actual_value:.1f}ms")
        print(f"  Status: {report.status.value}")
        print(f"  Samples: {report.samples}")
        
        # Verify SLO met
        assert report.actual_value <= 5000, \
            f"P95 delay {report.actual_value:.1f}ms exceeds 5000ms target"
        
        assert report.status == SLOStatus.HEALTHY
        
        print("\n" + "="*60)
        print(f"✅ ACCEPTANCE CRITERIA MET: P95 Queue Processing {report.actual_value:.1f}ms")
        print("="*60)
    
    @pytest.mark.asyncio
    async def test_slo_dashboard_generation(self, monitor):
        """Test comprehensive SLO dashboard"""
        
        # Generate dashboard
        dashboard = await monitor.generate_slo_dashboard()
        
        print(f"\n📊 SLO Dashboard:")
        print(f"  Overall Status: {dashboard['overall_status']}")
        print(f"  Healthy SLOs: {dashboard['summary']['healthy']}/{dashboard['summary']['total_slos']}")
        
        # Verify all metrics present
        assert "api_availability" in dashboard["slo_reports"]
        assert "challenge_issuance_latency" in dashboard["slo_reports"]
        assert "verify_accept_latency" in dashboard["slo_reports"]
        assert "queue_processing_delay" in dashboard["slo_reports"]
        
        print("✅ SLO dashboard generation validated")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])