"""
Verification Worker
Process jobs from queue with failure handling
"""

import asyncio
import asyncpg
import redis.asyncio as redis
import aioboto3
from typing import Dict, Any, Optional
from datetime import datetime
import logging
import traceback
import signal
import sys
import os

sys.path.insert(0, 'services/shared')

from pipeline_orchestrator import (
    AsyncPipelineOrchestrator,
    JobMetadata,
    JobResult,
    JobStatus
)

logger = logging.getLogger(__name__)


class VerificationWorker:
    """
    Verification Worker
    
    Responsibilities:
    1. Dequeue jobs from queue
    2. Download video from S3
    3. Process liveness detection
    4. Calculate risk score
    5. Store results
    6. Handle failures and retries
    
    Guarantees:
    - Worker failure does not lose job data
    - Jobs are retried on failure
    - Results are persisted before job completion
    """
    
    def __init__(
        self,
        worker_id: str,
        orchestrator: AsyncPipelineOrchestrator,
        s3_bucket: str,
        aws_region: str = "us-east-1"
    ):
        self.worker_id = worker_id
        self.orchestrator = orchestrator
        self.s3_bucket = s3_bucket
        self.aws_region = aws_region
        
        self.running = False
        self.current_job: Optional[JobMetadata] = None
        
        # Statistics
        self.jobs_processed = 0
        self.jobs_succeeded = 0
        self.jobs_failed = 0
    
    async def start(self):
        """
        Start worker processing loop
        
        Graceful shutdown on SIGTERM/SIGINT:
        - Finish current job before stopping
        - Return job to queue if interrupted
        """
        
        self.running = True
        
        # Register signal handlers
        signal.signal(signal.SIGTERM, self._handle_shutdown)
        signal.signal(signal.SIGINT, self._handle_shutdown)
        
        logger.info(
            f"🚀 Worker {self.worker_id} starting\n"
            f"   S3 Bucket: {self.s3_bucket}\n"
            f"   Region: {self.aws_region}"
        )
        
        while self.running:
            try:
                # Dequeue job (blocking with timeout)
                job_metadata = await self.orchestrator.dequeue_job(
                    worker_id=self.worker_id,
                    timeout_seconds=30
                )
                
                if not job_metadata:
                    # Timeout - no jobs available
                    logger.debug(f"⏳ Worker {self.worker_id} idle - no jobs")
                    continue
                
                self.current_job = job_metadata
                
                # Process job
                await self._process_job(job_metadata)
                
                self.current_job = None
                self.jobs_processed += 1
                
            except Exception as e:
                logger.error(f"❌ Worker {self.worker_id} error: {e}")
                logger.error(traceback.format_exc())
                
                # If we have a current job, handle failure
                if self.current_job:
                    await self._handle_job_failure(
                        self.current_job,
                        str(e),
                        "worker_exception"
                    )
                    self.current_job = None
                
                # Wait before retrying
                await asyncio.sleep(5)
        
        logger.info(
            f"🛑 Worker {self.worker_id} stopped\n"
            f"   Jobs Processed: {self.jobs_processed}\n"
            f"   Succeeded: {self.jobs_succeeded}\n"
            f"   Failed: {self.jobs_failed}"
        )
    
    def _handle_shutdown(self, signum, frame):
        """Handle graceful shutdown"""
        
        logger.info(f"🛑 Worker {self.worker_id} received shutdown signal")
        self.running = False
        
        # If processing a job, let it finish
        if self.current_job:
            logger.info(f"⏳ Finishing current job: {self.current_job.job_id}")
    
    async def _process_job(self, job_metadata: JobMetadata):
        """
        Process single job
        
        Steps:
        1. Download video from S3
        2. Process liveness detection
        3. Calculate risk score
        4. Store results
        5. Mark job complete or handle failure
        """
        
        start_time = datetime.utcnow()
        
        logger.info(
            f"⚙️  Processing job:\n"
            f"   Job ID: {job_metadata.job_id}\n"
            f"   Session: {job_metadata.session_id}\n"
            f"   S3 Key: {job_metadata.video_s3_key}"
        )
        
        try:
            # Step 1: Download video from S3
            video_data = await self._download_from_s3(job_metadata.video_s3_key)
            
            logger.info(f"   ✓ Downloaded {len(video_data):,} bytes from S3")
            
            # Step 2: Verify video integrity
            await self._verify_video_integrity(video_data, job_metadata.video_content_hash)
            
            logger.info(f"   ✓ Video integrity verified")
            
            # Step 3: Process liveness detection
            liveness_result = await self._process_liveness(video_data)
            
            logger.info(
                f"   ✓ Liveness detected: "
                f"{liveness_result['overall_liveness_score']:.2f}"
            )
            
            # Step 4: Calculate risk score
            risk_assessment = await self._calculate_risk_score(
                job_metadata.session_id,
                job_metadata.customer_id,
                liveness_result
            )
            
            logger.info(
                f"   ✓ Risk assessed: "
                f"{risk_assessment['overall_risk_score']:.2f}"
            )
            
            # Step 5: Determine decision
            decision = risk_assessment['decision']
            
            # Calculate processing duration
            end_time = datetime.utcnow()
            duration_ms = (end_time - start_time).total_seconds() * 1000
            
            # Step 6: Store results
            result = JobResult(
                job_id=job_metadata.job_id,
                session_id=job_metadata.session_id,
                success=True,
                liveness_result=liveness_result,
                risk_assessment=risk_assessment,
                decision=decision,
                processing_duration_ms=duration_ms,
                worker_id=self.worker_id,
                completed_at=end_time
            )
            
            await self.orchestrator.store_result(result)
            
            logger.info(
                f"✅ Job completed successfully:\n"
                f"   Job ID: {job_metadata.job_id}\n"
                f"   Decision: {decision}\n"
                f"   Duration: {duration_ms:.1f}ms"
            )
            
            self.jobs_succeeded += 1
            
        except Exception as e:
            logger.error(f"❌ Job processing failed: {e}")
            logger.error(traceback.format_exc())
            
            await self._handle_job_failure(
                job_metadata,
                str(e),
                type(e).__name__
            )
            
            self.jobs_failed += 1
    
    async def _download_from_s3(self, s3_key: str) -> bytes:
        """Download video from S3"""
        
        session = aioboto3.Session()
        
        async with session.client('s3', region_name=self.aws_region) as s3:
            response = await s3.get_object(
                Bucket=self.s3_bucket,
                Key=s3_key
            )
            
            async with response['Body'] as stream:
                video_data = await stream.read()
        
        return video_data
    
    async def _verify_video_integrity(self, video_data: bytes, expected_hash: str):
        """Verify video hasn't been corrupted"""
        
        import hashlib
        
        actual_hash = hashlib.sha256(video_data).hexdigest()
        
        if actual_hash != expected_hash:
            raise ValueError(
                f"Video integrity check failed: "
                f"expected {expected_hash}, got {actual_hash}"
            )
    
    async def _process_liveness(self, video_data: bytes) -> Dict[str, Any]:
        """
        Process liveness detection
        
        In production, this would:
        - Decode video frames
        - Run CV2 analysis
        - Run ML models
        - Aggregate results
        
        For this implementation, we'll simulate
        """
        
        # Simulate processing time
        await asyncio.sleep(0.8)
        
        # Simulate liveness detection result
        # In production: import from human_verification.py
        return {
            "overall_liveness_score": 0.92,
            "motion_score": 0.90,
            "temporal_score": 0.94,
            "anti_spoof_score": 0.91,
            "action_score": 0.93,
            "confidence": 0.89,
            "signals": {
                "head_movement_detected": True,
                "blink_detected": True,
                "depth_verified": True
            }
        }
    
    async def _calculate_risk_score(
        self,
        session_id: str,
        customer_id: str,
        liveness_result: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Calculate risk score
        
        In production: import from risk_scoring.py
        """
        
        # Simulate processing time
        await asyncio.sleep(0.1)
        
        # Simulate risk assessment
        return {
            "overall_risk_score": 0.18,
            "risk_level": "low",
            "decision": "approve",
            "passed": True,
            "factors": {
                "liveness": 0.08,
                "behavior": 0.05,
                "device": 0.03,
                "network": 0.02
            }
        }
    
    async def _handle_job_failure(
        self,
        job_metadata: JobMetadata,
        error_message: str,
        error_type: str
    ):
        """
        Handle job failure
        
        CRITICAL: This ensures worker failure does not lose job data
        Job is either retried or moved to dead letter queue
        """
        
        logger.warning(
            f"⚠️  Handling job failure:\n"
            f"   Job ID: {job_metadata.job_id}\n"
            f"   Error: {error_message}"
        )
        
        # Delegate to orchestrator for retry logic
        await self.orchestrator.handle_job_failure(
            job_metadata,
            error_message,
            error_type
        )


async def run_worker(
    worker_id: str,
    postgres_dsn: str,
    redis_url: str,
    s3_bucket: str,
    aws_region: str = "us-east-1"
):
    """
    Run verification worker
    
    Args:
        worker_id: Unique worker identifier
        postgres_dsn: PostgreSQL connection string
        redis_url: Redis connection URL
        s3_bucket: S3 bucket name
        aws_region: AWS region
    """
    
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Create connections
    postgres_pool = await asyncpg.create_pool(postgres_dsn, min_size=5, max_size=20)
    redis_client = await redis.from_url(redis_url)
    
    # Create orchestrator
    orchestrator = AsyncPipelineOrchestrator(
        postgres_pool=postgres_pool,
        redis_client=redis_client,
        s3_bucket=s3_bucket,
        aws_region=aws_region
    )
    
    # Create and start worker
    worker = VerificationWorker(
        worker_id=worker_id,
        orchestrator=orchestrator,
        s3_bucket=s3_bucket,
        aws_region=aws_region
    )
    
    try:
        await worker.start()
    finally:
        await postgres_pool.close()
        await redis_client.close()


if __name__ == "__main__":
    import uuid
    
    worker_id = f"worker-{uuid.uuid4().hex[:8]}"
    
    asyncio.run(run_worker(
        worker_id=worker_id,
        postgres_dsn=os.getenv("POSTGRES_DSN", "postgresql://certivo:certivo@localhost:5432/certivo"),
        redis_url=os.getenv("REDIS_URL", "redis://localhost:6379"),
        s3_bucket=os.getenv("S3_BUCKET", "certivo-videos-dev"),
        aws_region=os.getenv("AWS_REGION", "us-east-1")
    ))