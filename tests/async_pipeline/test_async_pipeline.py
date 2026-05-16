"""
Async Pipeline Tests

Acceptance Criteria:
1. Worker failure does not lose job data
2. End-to-end exactly-once/at-least-once semantics documented and tested
"""

import pytest
import asyncio
import asyncpg
import redis.asyncio as redis
from datetime import datetime
import sys
import os

sys.path.insert(0, 'services/async_pipeline')

from pipeline_orchestrator import (
    AsyncPipelineOrchestrator,
    JobMetadata,
    JobResult,
    JobStatus,
    JobPriority
)
from verification_worker import VerificationWorker


class TestAsyncPipeline:
    """Test async pipeline orchestration"""
    
    @pytest.fixture
    async def orchestrator(self):
        """Setup orchestrator"""
        
        postgres_pool = await asyncpg.create_pool(
            "postgresql://certivo:certivo@localhost:5432/certivo"
        )
        
        redis_client = await redis.from_url("redis://localhost:6379")
        
        orchestrator = AsyncPipelineOrchestrator(
            postgres_pool=postgres_pool,
            redis_client=redis_client,
            s3_bucket="certivo-test-bucket",
            aws_region="us-east-1"
        )
        
        yield orchestrator
        
        await postgres_pool.close()
        await redis_client.close()
    
    @pytest.mark.asyncio
    async def test_upload_and_enqueue(self, orchestrator):
        """Test video upload and job enqueue"""
        
        video_data = b'\x00' * (5 * 1024 * 1024)  # 5 MB video
        
        job_metadata = await orchestrator.upload_and_enqueue(
            session_id="SES-TEST-001",
            customer_id="CUST-TEST-001",
            video_data=video_data,
            priority=JobPriority.NORMAL
        )
        
        assert job_metadata.job_id is not None
        assert job_metadata.status == JobStatus.QUEUED
        assert job_metadata.video_size_bytes == len(video_data)
        
        print(f"✅ Job created and enqueued: {job_metadata.job_id}")
    
    @pytest.mark.asyncio
    async def test_exactly_once_job_creation(self, orchestrator):
        """
        Test exactly-once job creation via idempotency
        
        Same idempotency key should return same job
        """
        
        print("\n" + "="*60)
        print("TEST: Exactly-Once Job Creation")
        print("="*60)
        
        video_data = b'\x00' * (3 * 1024 * 1024)
        idempotency_key = "IDEMPOTENCY-TEST-001"
        
        # First submission
        job1 = await orchestrator.upload_and_enqueue(
            session_id="SES-IDEMPOTENT-001",
            customer_id="CUST-TEST-001",
            video_data=video_data,
            idempotency_key=idempotency_key
        )
        
        print(f"\n✓ First submission: {job1.job_id}")
        
        # Second submission (duplicate)
        job2 = await orchestrator.upload_and_enqueue(
            session_id="SES-IDEMPOTENT-002",  # Different session
            customer_id="CUST-TEST-001",
            video_data=video_data,
            idempotency_key=idempotency_key  # Same key
        )
        
        print(f"✓ Second submission: {job2.job_id}")
        
        # Should return same job
        assert job1.job_id == job2.job_id
        
        print(f"\n✅ Exactly-once semantics verified: {job1.job_id} == {job2.job_id}")
        print("="*60)
    
    @pytest.mark.asyncio
    async def test_dequeue_job(self, orchestrator):
        """Test job dequeuing"""
        
        # Enqueue job
        video_data = b'\x00' * (4 * 1024 * 1024)
        
        job_metadata = await orchestrator.upload_and_enqueue(
            session_id="SES-DEQUEUE-001",
            customer_id="CUST-TEST-001",
            video_data=video_data
        )
        
        print(f"\n✓ Job enqueued: {job_metadata.job_id}")
        
        # Dequeue job
        dequeued_job = await orchestrator.dequeue_job(
            worker_id="test-worker-001",
            timeout_seconds=5
        )
        
        assert dequeued_job is not None
        assert dequeued_job.job_id == job_metadata.job_id
        assert dequeued_job.status == JobStatus.PROCESSING
        
        print(f"✅ Job dequeued: {dequeued_job.job_id}")
    
    @pytest.mark.asyncio
    async def test_store_result(self, orchestrator):
        """Test result storage"""
        
        result = JobResult(
            job_id="JOB-RESULT-TEST-001",
            session_id="SES-RESULT-001",
            success=True,
            liveness_result={"overall_liveness_score": 0.95},
            risk_assessment={"overall_risk_score": 0.12},
            decision="approve",
            processing_duration_ms=1234.5,
            worker_id="test-worker-001"
        )
        
        await orchestrator.store_result(result)
        
        # Verify stored
        status = await orchestrator.get_job_status(result.job_id)
        
        assert status is not None
        assert status["result"]["success"] == True
        assert status["result"]["decision"] == "approve"
        
        print(f"✅ Result stored for job: {result.job_id}")
    
    @pytest.mark.asyncio
    async def test_job_retry_on_failure(self, orchestrator):
        """
        ACCEPTANCE CRITERIA 1: Worker failure does not lose job data
        
        Test job is retried when worker fails
        """
        
        print("\n" + "="*60)
        print("ACCEPTANCE TEST: Worker Failure - Job Not Lost")
        print("="*60)
        
        # Create job
        video_data = b'\x00' * (2 * 1024 * 1024)
        
        job_metadata = await orchestrator.upload_and_enqueue(
            session_id="SES-RETRY-001",
            customer_id="CUST-TEST-001",
            video_data=video_data
        )
        
        print(f"\n✓ Job created: {job_metadata.job_id}")
        print(f"  Initial retry count: {job_metadata.retry_count}")
        
        # Dequeue job
        dequeued_job = await orchestrator.dequeue_job(
            worker_id="failing-worker-001",
            timeout_seconds=5
        )
        
        print(f"\n✓ Job dequeued by worker")
        
        # Simulate worker failure
        await orchestrator.handle_job_failure(
            dequeued_job,
            error_message="Worker crashed during processing",
            error_type="worker_crash"
        )
        
        print(f"\n✓ Worker failure handled")
        
        # Verify job was moved to retry queue
        async with orchestrator.postgres.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM job_metadata WHERE job_id = $1",
                job_metadata.job_id
            )
        
        assert row is not None
        assert row["status"] == JobStatus.RETRYING.value
        assert row["retry_count"] == 1
        assert row["last_error"] == "Worker crashed during processing"
        
        print(f"\n✓ Job moved to retry queue:")
        print(f"  Status: {row['status']}")
        print(f"  Retry count: {row['retry_count']}")
        print(f"  Last error: {row['last_error']}")
        
        print("\n" + "="*60)
        print("✅ ACCEPTANCE CRITERIA MET: Job Not Lost on Worker Failure")
        print("="*60)
    
    @pytest.mark.asyncio
    async def test_max_retries_dead_letter(self, orchestrator):
        """
        Test job moved to dead letter queue after max retries
        """
        
        print("\n" + "="*60)
        print("TEST: Dead Letter Queue After Max Retries")
        print("="*60)
        
        # Create job
        video_data = b'\x00' * (1 * 1024 * 1024)
        
        job_metadata = await orchestrator.upload_and_enqueue(
            session_id="SES-DEAD-LETTER-001",
            customer_id="CUST-TEST-001",
            video_data=video_data
        )
        
        print(f"\n✓ Job created: {job_metadata.job_id}")
        print(f"  Max retries: {job_metadata.max_retries}")
        
        # Fail job max_retries times
        for i in range(job_metadata.max_retries):
            # Dequeue
            dequeued_job = await orchestrator.dequeue_job(
                worker_id=f"worker-{i}",
                timeout_seconds=5
            )
            
            # Fail
            await orchestrator.handle_job_failure(
                dequeued_job,
                error_message=f"Failure {i+1}",
                error_type="test_failure"
            )
            
            print(f"\n✓ Retry {i+1}/{job_metadata.max_retries} failed")
            
            # Wait for retry queue processing
            await asyncio.sleep(1)
        
        # Dequeue one more time (should trigger dead letter)
        dequeued_job = await orchestrator.dequeue_job(
            worker_id="final-worker",
            timeout_seconds=5
        )
        
        # Final failure
        await orchestrator.handle_job_failure(
            dequeued_job,
            error_message="Final failure",
            error_type="test_failure"
        )
        
        # Verify in dead letter queue
        async with orchestrator.postgres.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM job_metadata WHERE job_id = $1",
                job_metadata.job_id
            )
        
        assert row["status"] == JobStatus.DEAD_LETTER.value
        assert row["retry_count"] >= job_metadata.max_retries
        
        print(f"\n✓ Job moved to dead letter queue:")
        print(f"  Status: {row['status']}")
        print(f"  Final retry count: {row['retry_count']}")
        
        print("\n" + "="*60)
        print("✅ Dead Letter Queue Working Correctly")
        print("="*60)
    
    @pytest.mark.asyncio
    async def test_poll_result(self, orchestrator):
        """Test polling for job result"""
        
        # Create and store result
        job_id = "JOB-POLL-TEST-001"
        
        result = JobResult(
            job_id=job_id,
            session_id="SES-POLL-001",
            success=True,
            liveness_result={"overall_liveness_score": 0.88},
            decision="approve",
            processing_duration_ms=987.6,
            worker_id="test-worker"
        )
        
        # Store result in background
        async def store_after_delay():
            await asyncio.sleep(2)
            await orchestrator.store_result(result)
        
        asyncio.create_task(store_after_delay())
        
        # Poll for result
        polled_result = await orchestrator.poll_result(
            job_id=job_id,
            timeout_seconds=10
        )
        
        assert polled_result is not None
        assert polled_result.job_id == job_id
        assert polled_result.success == True
        
        print(f"✅ Result polled successfully: {job_id}")


class TestEndToEndSemantics:
    """
    ACCEPTANCE CRITERIA 2: End-to-end exactly-once/at-least-once semantics
    """
    
    @pytest.fixture
    async def orchestrator(self):
        """Setup orchestrator"""
        
        postgres_pool = await asyncpg.create_pool(
            "postgresql://certivo:certivo@localhost:5432/certivo"
        )
        
        redis_client = await redis.from_url("redis://localhost:6379")
        
        orchestrator = AsyncPipelineOrchestrator(
            postgres_pool=postgres_pool,
            redis_client=redis_client,
            s3_bucket="certivo-test-bucket",
            aws_region="us-east-1"
        )
        
        yield orchestrator
        
        await postgres_pool.close()
        await redis_client.close()
    
    @pytest.mark.asyncio
    async def test_exactly_once_semantics(self, orchestrator):
        """
        ACCEPTANCE CRITERIA 2: Exactly-once job creation
        
        Test that duplicate submissions with same idempotency key
        result in exactly one job being created
        """
        
        print("\n" + "="*60)
        print("ACCEPTANCE TEST: Exactly-Once Job Creation Semantics")
        print("="*60)
        
        video_data = b'\x00' * (3 * 1024 * 1024)
        idempotency_key = "EXACTLY-ONCE-TEST"
        
        # Submit 10 times with same idempotency key
        job_ids = []
        
        for i in range(10):
            job = await orchestrator.upload_and_enqueue(
                session_id=f"SES-EXACTLY-ONCE-{i}",
                customer_id="CUST-TEST-001",
                video_data=video_data,
                idempotency_key=idempotency_key
            )
            job_ids.append(job.job_id)
            
            print(f"  Submission {i+1}: {job.job_id}")
        
        # All should be the same job
        unique_job_ids = set(job_ids)
        
        print(f"\n✓ Total submissions: 10")
        print(f"✓ Unique jobs created: {len(unique_job_ids)}")
        
        assert len(unique_job_ids) == 1, \
            f"Expected exactly 1 job, got {len(unique_job_ids)}"
        
        print("\n" + "="*60)
        print("✅ ACCEPTANCE CRITERIA MET: Exactly-Once Semantics")
        print("="*60)
    
    @pytest.mark.asyncio
    async def test_at_least_once_processing(self, orchestrator):
        """
        ACCEPTANCE CRITERIA 2: At-least-once processing
        
        Test that job is processed at least once even if worker fails
        """
        
        print("\n" + "="*60)
        print("ACCEPTANCE TEST: At-Least-Once Processing Semantics")
        print("="*60)
        
        # Create job
        video_data = b'\x00' * (2 * 1024 * 1024)
        
        job = await orchestrator.upload_and_enqueue(
            session_id="SES-AT-LEAST-ONCE",
            customer_id="CUST-TEST-001",
            video_data=video_data
        )
        
        print(f"\n✓ Job created: {job.job_id}")
        
        processing_attempts = 0
        
        # Simulate multiple processing attempts due to failures
        for attempt in range(3):
            # Dequeue job
            dequeued_job = await orchestrator.dequeue_job(
                worker_id=f"worker-{attempt}",
                timeout_seconds=5
            )
            
            if dequeued_job:
                processing_attempts += 1
                print(f"\n✓ Processing attempt {processing_attempts}")
                
                if attempt < 2:
                    # Fail first 2 attempts
                    await orchestrator.handle_job_failure(
                        dequeued_job,
                        error_message=f"Simulated failure {attempt+1}",
                        error_type="test_failure"
                    )
                    print(f"  ✗ Attempt {attempt+1} failed")
                    
                    # Wait for retry
                    await asyncio.sleep(3)
                else:
                    # Succeed on 3rd attempt
                    result = JobResult(
                        job_id=dequeued_job.job_id,
                        session_id=dequeued_job.session_id,
                        success=True,
                        decision="approve",
                        processing_duration_ms=1000.0,
                        worker_id=f"worker-{attempt}"
                    )
                    
                    await orchestrator.store_result(result)
                    print(f"  ✓ Attempt {attempt+1} succeeded")
        
        print(f"\n✓ Total processing attempts: {processing_attempts}")
        
        # Verify at least one successful processing
        assert processing_attempts >= 1, \
            "Job should be processed at least once"
        
        # Verify final result
        status = await orchestrator.get_job_status(job.job_id)
        assert status["result"]["success"] == True
        
        print("\n" + "="*60)
        print("✅ ACCEPTANCE CRITERIA MET: At-Least-Once Processing")
        print("="*60)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])