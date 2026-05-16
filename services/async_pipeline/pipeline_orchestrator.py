"""
Async Pipeline Orchestrator
Handles upload -> storage -> queue -> worker -> result flow
"""

import asyncio
import asyncpg
import redis.asyncio as redis
import aioboto3
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
import json
import logging
import hashlib
import uuid

logger = logging.getLogger(__name__)


class JobStatus(str, Enum):
    """Job processing status"""
    PENDING = "pending"           # Job created, not queued yet
    QUEUED = "queued"            # Job in queue
    PROCESSING = "processing"     # Worker is processing
    COMPLETED = "completed"       # Successfully completed
    FAILED = "failed"            # Failed permanently
    RETRYING = "retrying"        # Failed, will retry
    DEAD_LETTER = "dead_letter"  # Moved to dead letter queue


class JobPriority(str, Enum):
    """Job priority levels"""
    HIGH = "high"       # Real-time verification
    NORMAL = "normal"   # Standard processing
    LOW = "low"         # Background tasks


@dataclass
class JobMetadata:
    """Job metadata for tracking"""
    job_id: str
    session_id: str
    customer_id: str
    
    # Upload info
    video_s3_key: str
    video_size_bytes: int
    video_content_hash: str
    
    # Processing info
    priority: JobPriority
    max_retries: int = 3
    retry_count: int = 0
    
    # Timestamps
    created_at: datetime = field(default_factory=datetime.utcnow)
    queued_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    
    # Status
    status: JobStatus = JobStatus.PENDING
    
    # Error tracking
    last_error: Optional[str] = None
    error_history: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "job_id": self.job_id,
            "session_id": self.session_id,
            "customer_id": self.customer_id,
            "video_s3_key": self.video_s3_key,
            "video_size_bytes": self.video_size_bytes,
            "video_content_hash": self.video_content_hash,
            "priority": self.priority.value,
            "max_retries": self.max_retries,
            "retry_count": self.retry_count,
            "created_at": self.created_at.isoformat(),
            "queued_at": self.queued_at.isoformat() if self.queued_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "status": self.status.value,
            "last_error": self.last_error,
            "error_history": self.error_history
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'JobMetadata':
        return cls(
            job_id=data["job_id"],
            session_id=data["session_id"],
            customer_id=data["customer_id"],
            video_s3_key=data["video_s3_key"],
            video_size_bytes=data["video_size_bytes"],
            video_content_hash=data["video_content_hash"],
            priority=JobPriority(data["priority"]),
            max_retries=data["max_retries"],
            retry_count=data["retry_count"],
            created_at=datetime.fromisoformat(data["created_at"]),
            queued_at=datetime.fromisoformat(data["queued_at"]) if data.get("queued_at") else None,
            started_at=datetime.fromisoformat(data["started_at"]) if data.get("started_at") else None,
            completed_at=datetime.fromisoformat(data["completed_at"]) if data.get("completed_at") else None,
            status=JobStatus(data["status"]),
            last_error=data.get("last_error"),
            error_history=data.get("error_history", [])
        )


@dataclass
class JobResult:
    """Job processing result"""
    job_id: str
    session_id: str
    
    success: bool
    
    # Verification result
    liveness_result: Optional[Dict[str, Any]] = None
    risk_assessment: Optional[Dict[str, Any]] = None
    decision: Optional[str] = None
    
    # Processing metadata
    processing_duration_ms: float = 0.0
    worker_id: Optional[str] = None
    
    # Error info
    error_message: Optional[str] = None
    error_type: Optional[str] = None
    
    completed_at: datetime = field(default_factory=datetime.utcnow)


class AsyncPipelineOrchestrator:
    """
    Async Pipeline Orchestrator
    
    Flow:
    1. Upload video to S3
    2. Create job metadata in DB
    3. Enqueue job to SQS/Redis
    4. Worker picks up job
    5. Worker processes video
    6. Worker stores results
    7. Worker sends callback/result available
    
    Features:
    - Exactly-once job creation
    - At-least-once processing
    - Automatic retries with exponential backoff
    - Poison queue for persistent failures
    - Dead letter queue for max retries exceeded
    - Job status tracking
    """
    
    def __init__(
        self,
        postgres_pool: asyncpg.Pool,
        redis_client: redis.Redis,
        s3_bucket: str,
        aws_region: str = "us-east-1"
    ):
        self.postgres = postgres_pool
        self.redis = redis_client
        self.s3_bucket = s3_bucket
        self.aws_region = aws_region
        
        # Queue names
        self.primary_queue = "verification_jobs"
        self.retry_queue = "verification_jobs_retry"
        self.dead_letter_queue = "verification_jobs_dead_letter"
        self.poison_queue = "verification_jobs_poison"
    
    async def upload_and_enqueue(
        self,
        session_id: str,
        customer_id: str,
        video_data: bytes,
        priority: JobPriority = JobPriority.NORMAL,
        idempotency_key: Optional[str] = None
    ) -> JobMetadata:
        """
        Step 1-3: Upload video, create job, enqueue
        
        Guarantees:
        - Exactly-once job creation (via idempotency key)
        - Video uploaded before job queued
        - Job metadata persisted before queuing
        
        Args:
            session_id: Session identifier
            customer_id: Customer identifier
            video_data: Video bytes
            priority: Job priority
            idempotency_key: Optional idempotency key (defaults to session_id)
        
        Returns:
            Job metadata
        """
        
        # Use session_id as idempotency key if not provided
        if idempotency_key is None:
            idempotency_key = session_id
        
        # Check for existing job (exactly-once)
        existing_job = await self._get_job_by_idempotency_key(idempotency_key)
        if existing_job:
            logger.info(f"📋 Job already exists for idempotency key: {idempotency_key}")
            return existing_job
        
        # Generate job ID
        job_id = f"JOB-{uuid.uuid4()}"
        
        # Calculate content hash
        content_hash = hashlib.sha256(video_data).hexdigest()
        
        # Generate S3 key
        s3_key = f"videos/{customer_id}/{session_id}/{job_id}.mp4"
        
        logger.info(
            f"🚀 Starting async pipeline:\n"
            f"   Job ID: {job_id}\n"
            f"   Session: {session_id}\n"
            f"   Video Size: {len(video_data):,} bytes\n"
            f"   Priority: {priority.value}"
        )
        
        # Step 1: Upload to S3
        await self._upload_to_s3(s3_key, video_data)
        
        logger.info(f"✅ Step 1: Video uploaded to S3: {s3_key}")
        
        # Step 2: Create job metadata in DB
        job_metadata = JobMetadata(
            job_id=job_id,
            session_id=session_id,
            customer_id=customer_id,
            video_s3_key=s3_key,
            video_size_bytes=len(video_data),
            video_content_hash=content_hash,
            priority=priority,
            status=JobStatus.PENDING
        )
        
        await self._create_job_metadata(job_metadata, idempotency_key)
        
        logger.info(f"✅ Step 2: Job metadata created in DB")
        
        # Step 3: Enqueue job
        await self._enqueue_job(job_metadata)
        
        logger.info(f"✅ Step 3: Job enqueued to {self.primary_queue}")
        
        return job_metadata
    
    async def _upload_to_s3(self, s3_key: str, video_data: bytes):
        """Upload video to S3"""
        
        session = aioboto3.Session()
        
        async with session.client('s3', region_name=self.aws_region) as s3:
            await s3.put_object(
                Bucket=self.s3_bucket,
                Key=s3_key,
                Body=video_data,
                ContentType='video/mp4',
                ServerSideEncryption='AES256',
                Metadata={
                    'uploaded_at': datetime.utcnow().isoformat()
                }
            )
    
    async def _create_job_metadata(
        self,
        job_metadata: JobMetadata,
        idempotency_key: str
    ):
        """
        Create job metadata in database
        
        Ensures exactly-once job creation via idempotency key
        """
        
        async with self.postgres.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO job_metadata
                (job_id, session_id, customer_id, video_s3_key, 
                 video_size_bytes, video_content_hash, priority, 
                 max_retries, retry_count, status, created_at, idempotency_key)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
                ON CONFLICT (idempotency_key) DO NOTHING
                """,
                job_metadata.job_id,
                job_metadata.session_id,
                job_metadata.customer_id,
                job_metadata.video_s3_key,
                job_metadata.video_size_bytes,
                job_metadata.video_content_hash,
                job_metadata.priority.value,
                job_metadata.max_retries,
                job_metadata.retry_count,
                job_metadata.status.value,
                job_metadata.created_at,
                idempotency_key
            )
    
    async def _get_job_by_idempotency_key(
        self,
        idempotency_key: str
    ) -> Optional[JobMetadata]:
        """Get existing job by idempotency key"""
        
        async with self.postgres.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT * FROM job_metadata
                WHERE idempotency_key = $1
                """,
                idempotency_key
            )
        
        if row:
            return JobMetadata.from_dict(dict(row))
        
        return None
    
    async def _enqueue_job(self, job_metadata: JobMetadata):
        """
        Enqueue job to Redis queue
        
        Uses priority queues for different job priorities
        """
        
        # Determine queue based on priority
        if job_metadata.priority == JobPriority.HIGH:
            queue_key = f"{self.primary_queue}:high"
        elif job_metadata.priority == JobPriority.LOW:
            queue_key = f"{self.primary_queue}:low"
        else:
            queue_key = f"{self.primary_queue}:normal"
        
        # Update status to queued
        job_metadata.status = JobStatus.QUEUED
        job_metadata.queued_at = datetime.utcnow()
        
        await self._update_job_status(
            job_metadata.job_id,
            JobStatus.QUEUED,
            queued_at=job_metadata.queued_at
        )
        
        # Push to Redis queue
        await self.redis.lpush(
            queue_key,
            json.dumps(job_metadata.to_dict())
        )
        
        # Also store in hash for quick lookup
        await self.redis.hset(
            "jobs:metadata",
            job_metadata.job_id,
            json.dumps(job_metadata.to_dict())
        )
        
        # Set expiry (7 days)
        await self.redis.expire(f"jobs:metadata:{job_metadata.job_id}", 7 * 86400)
    
    async def _update_job_status(
        self,
        job_id: str,
        status: JobStatus,
        **kwargs
    ):
        """Update job status in database"""
        
        # Build update query dynamically
        updates = ["status = $2"]
        params = [job_id, status.value]
        param_idx = 3
        
        for field, value in kwargs.items():
            updates.append(f"{field} = ${param_idx}")
            params.append(value)
            param_idx += 1
        
        query = f"""
            UPDATE job_metadata
            SET {', '.join(updates)}
            WHERE job_id = $1
        """
        
        async with self.postgres.acquire() as conn:
            await conn.execute(query, *params)
    
    async def dequeue_job(
        self,
        worker_id: str,
        timeout_seconds: int = 30
    ) -> Optional[JobMetadata]:
        """
        Dequeue job for processing
        
        Priority order: high > normal > low
        
        Args:
            worker_id: Worker identifier
            timeout_seconds: Blocking timeout
        
        Returns:
            Job metadata or None if timeout
        """
        
        # Try high priority first
        job_data = await self.redis.brpop(
            f"{self.primary_queue}:high",
            timeout=1
        )
        
        # Then normal
        if not job_data:
            job_data = await self.redis.brpop(
                f"{self.primary_queue}:normal",
                timeout=1
            )
        
        # Then low
        if not job_data:
            job_data = await self.redis.brpop(
                f"{self.primary_queue}:low",
                timeout=timeout_seconds
            )
        
        if not job_data:
            return None
        
        # Parse job metadata
        _, job_json = job_data
        job_metadata = JobMetadata.from_dict(json.loads(job_json))
        
        # Update status to processing
        job_metadata.status = JobStatus.PROCESSING
        job_metadata.started_at = datetime.utcnow()
        
        await self._update_job_status(
            job_metadata.job_id,
            JobStatus.PROCESSING,
            started_at=job_metadata.started_at
        )
        
        # Store processing lock (prevent duplicate processing)
        await self.redis.setex(
            f"jobs:processing:{job_metadata.job_id}",
            300,  # 5 minute lock
            worker_id
        )
        
        logger.info(
            f"📥 Job dequeued by worker {worker_id}:\n"
            f"   Job ID: {job_metadata.job_id}\n"
            f"   Session: {job_metadata.session_id}\n"
            f"   Retry Count: {job_metadata.retry_count}/{job_metadata.max_retries}"
        )
        
        return job_metadata
    
    async def store_result(
        self,
        result: JobResult
    ):
        """
        Store job result
        
        Args:
            result: Job processing result
        """
        
        logger.info(
            f"💾 Storing result:\n"
            f"   Job ID: {result.job_id}\n"
            f"   Success: {result.success}\n"
            f"   Duration: {result.processing_duration_ms:.1f}ms"
        )
        
        # Store in database
        async with self.postgres.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO job_results
                (job_id, session_id, success, liveness_result, 
                 risk_assessment, decision, processing_duration_ms, 
                 worker_id, error_message, error_type, completed_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                """,
                result.job_id,
                result.session_id,
                result.success,
                json.dumps(result.liveness_result) if result.liveness_result else None,
                json.dumps(result.risk_assessment) if result.risk_assessment else None,
                result.decision,
                result.processing_duration_ms,
                result.worker_id,
                result.error_message,
                result.error_type,
                result.completed_at
            )
        
        # Update job status
        if result.success:
            await self._update_job_status(
                result.job_id,
                JobStatus.COMPLETED,
                completed_at=result.completed_at
            )
        else:
            await self._update_job_status(
                result.job_id,
                JobStatus.FAILED,
                completed_at=result.completed_at,
                last_error=result.error_message
            )
        
        # Store in Redis for quick access
        await self.redis.setex(
            f"jobs:result:{result.job_id}",
            7 * 86400,  # 7 days
            json.dumps({
                "success": result.success,
                "decision": result.decision,
                "completed_at": result.completed_at.isoformat()
            })
        )
        
        # Remove processing lock
        await self.redis.delete(f"jobs:processing:{result.job_id}")
    
    async def handle_job_failure(
        self,
        job_metadata: JobMetadata,
        error_message: str,
        error_type: str = "processing_error"
    ):
        """
        Handle job failure with retry logic
        
        Flow:
        1. Increment retry count
        2. If retries < max_retries: Move to retry queue
        3. If retries >= max_retries: Move to dead letter queue
        4. Update job status
        
        Args:
            job_metadata: Job metadata
            error_message: Error description
            error_type: Error type classification
        """
        
        job_metadata.retry_count += 1
        job_metadata.last_error = error_message
        job_metadata.error_history.append(
            f"[{datetime.utcnow().isoformat()}] {error_type}: {error_message}"
        )
        
        logger.warning(
            f"⚠️  Job failed:\n"
            f"   Job ID: {job_metadata.job_id}\n"
            f"   Error: {error_message}\n"
            f"   Retry: {job_metadata.retry_count}/{job_metadata.max_retries}"
        )
        
        if job_metadata.retry_count < job_metadata.max_retries:
            # Retry with exponential backoff
            await self._enqueue_for_retry(job_metadata)
        else:
            # Max retries exceeded - move to dead letter queue
            await self._move_to_dead_letter(job_metadata)
    
    async def _enqueue_for_retry(self, job_metadata: JobMetadata):
        """
        Enqueue job for retry with exponential backoff
        
        Backoff: 2^retry_count seconds (1s, 2s, 4s, 8s, ...)
        """
        
        job_metadata.status = JobStatus.RETRYING
        
        # Calculate backoff delay
        backoff_seconds = 2 ** job_metadata.retry_count
        retry_at = datetime.utcnow() + timedelta(seconds=backoff_seconds)
        
        logger.info(
            f"🔄 Enqueueing for retry:\n"
            f"   Job ID: {job_metadata.job_id}\n"
            f"   Retry Count: {job_metadata.retry_count}\n"
            f"   Backoff: {backoff_seconds}s\n"
            f"   Retry At: {retry_at.isoformat()}"
        )
        
        # Update database
        await self._update_job_status(
            job_metadata.job_id,
            JobStatus.RETRYING,
            retry_count=job_metadata.retry_count,
            last_error=job_metadata.last_error
        )
        
        # Add to sorted set with retry timestamp as score
        await self.redis.zadd(
            self.retry_queue,
            {json.dumps(job_metadata.to_dict()): retry_at.timestamp()}
        )
        
        # Remove processing lock
        await self.redis.delete(f"jobs:processing:{job_metadata.job_id}")
    
    async def _move_to_dead_letter(self, job_metadata: JobMetadata):
        """
        Move job to dead letter queue (max retries exceeded)
        """
        
        job_metadata.status = JobStatus.DEAD_LETTER
        
        logger.error(
            f"💀 Moving to dead letter queue:\n"
            f"   Job ID: {job_metadata.job_id}\n"
            f"   Retries: {job_metadata.retry_count}\n"
            f"   Last Error: {job_metadata.last_error}"
        )
        
        # Update database
        await self._update_job_status(
            job_metadata.job_id,
            JobStatus.DEAD_LETTER,
            retry_count=job_metadata.retry_count,
            last_error=job_metadata.last_error
        )
        
        # Add to dead letter queue
        await self.redis.lpush(
            self.dead_letter_queue,
            json.dumps(job_metadata.to_dict())
        )
        
        # Remove processing lock
        await self.redis.delete(f"jobs:processing:{job_metadata.job_id}")
    
    async def process_retry_queue(self):
        """
        Process retry queue - move ready jobs back to primary queue
        
        Should be run periodically (e.g., every 10 seconds)
        """
        
        now = datetime.utcnow().timestamp()
        
        # Get jobs ready for retry
        ready_jobs = await self.redis.zrangebyscore(
            self.retry_queue,
            0,
            now
        )
        
        for job_json in ready_jobs:
            job_metadata = JobMetadata.from_dict(json.loads(job_json))
            
            logger.info(f"🔄 Moving job {job_metadata.job_id} from retry to primary queue")
            
            # Re-enqueue to primary queue
            await self._enqueue_job(job_metadata)
            
            # Remove from retry queue
            await self.redis.zrem(self.retry_queue, job_json)
    
    async def get_job_status(self, job_id: str) -> Optional[Dict[str, Any]]:
        """
        Get current job status
        
        Args:
            job_id: Job identifier
        
        Returns:
            Job status info or None if not found
        """
        
        # Try Redis first (faster)
        job_json = await self.redis.hget("jobs:metadata", job_id)
        
        if job_json:
            job_metadata = JobMetadata.from_dict(json.loads(job_json))
            
            # Check if result available
            result_json = await self.redis.get(f"jobs:result:{job_id}")
            result = json.loads(result_json) if result_json else None
            
            return {
                "job_id": job_id,
                "status": job_metadata.status.value,
                "retry_count": job_metadata.retry_count,
                "created_at": job_metadata.created_at.isoformat(),
                "result": result
            }
        
        # Fall back to database
        async with self.postgres.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT jm.*, jr.success, jr.decision
                FROM job_metadata jm
                LEFT JOIN job_results jr ON jm.job_id = jr.job_id
                WHERE jm.job_id = $1
                """,
                job_id
            )
        
        if row:
            return {
                "job_id": job_id,
                "status": row["status"],
                "retry_count": row["retry_count"],
                "created_at": row["created_at"].isoformat(),
                "result": {
                    "success": row["success"],
                    "decision": row["decision"]
                } if row["success"] is not None else None
            }
        
        return None
    
    async def poll_result(
        self,
        job_id: str,
        timeout_seconds: int = 30
    ) -> Optional[JobResult]:
        """
        Poll for job result with timeout
        
        Args:
            job_id: Job identifier
            timeout_seconds: Max time to wait
        
        Returns:
            Job result or None if timeout
        """
        
        start_time = datetime.utcnow()
        
        while (datetime.utcnow() - start_time).total_seconds() < timeout_seconds:
            # Check for result
            result_json = await self.redis.get(f"jobs:result:{job_id}")
            
            if result_json:
                result_data = json.loads(result_json)
                
                # Get full result from database
                async with self.postgres.acquire() as conn:
                    row = await conn.fetchrow(
                        """
                        SELECT * FROM job_results
                        WHERE job_id = $1
                        """,
                        job_id
                    )
                
                if row:
                    return JobResult(
                        job_id=row["job_id"],
                        session_id=row["session_id"],
                        success=row["success"],
                        liveness_result=json.loads(row["liveness_result"]) if row["liveness_result"] else None,
                        risk_assessment=json.loads(row["risk_assessment"]) if row["risk_assessment"] else None,
                        decision=row["decision"],
                        processing_duration_ms=row["processing_duration_ms"],
                        worker_id=row["worker_id"],
                        error_message=row["error_message"],
                        error_type=row["error_type"],
                        completed_at=row["completed_at"]
                    )
            
            # Wait before next poll
            await asyncio.sleep(0.5)
        
        return None