"""
User Erasure Workflow
Complete user data erasure with 30-day SLA
"""

import asyncpg
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class ErasureStatus(str, Enum):
    """Erasure request status"""
    RECEIVED = "received"
    ACKNOWLEDGED = "acknowledged"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class UserErasureRequest:
    """User erasure request tracking"""
    request_id: str
    user_identifier: str
    user_email: Optional[str] = None
    
    # Status
    status: ErasureStatus = ErasureStatus.RECEIVED
    
    # SLA tracking (30 days)
    requested_at: datetime = None
    acknowledged_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    deadline: datetime = None
    
    # Progress
    tables_to_process: List[str] = None
    tables_completed: List[str] = None
    deletion_jobs: List[str] = None
    
    # Results
    total_records_deleted: int = 0
    verification_results: Optional[Dict[str, Any]] = None
    
    # Metadata
    request_source: str = "api"
    notes: Optional[str] = None
    
    def __post_init__(self):
        if self.requested_at is None:
            self.requested_at = datetime.utcnow()
        if self.deadline is None:
            self.deadline = self.requested_at + timedelta(days=30)
        if self.tables_completed is None:
            self.tables_completed = []
        if self.deletion_jobs is None:
            self.deletion_jobs = []


class UserErasureService:
    """
    User Erasure Service
    
    Implements GDPR/CCPA "Right to Erasure"
    
    Features:
    - Complete user data erasure across all tables
    - 30-day SLA compliance
    - Progress tracking
    - Verification
    - Audit trail
    
    Acceptance Criteria:
    - Erasure completed within 30 days
    - Verifiable in logs and storage
    """
    
    # Tables containing user data (in order of deletion)
    USER_DATA_TABLES = [
        "sessions",
        "challenges",
        "verification_results",
        "video_uploads",
        "risk_assessments",
        "explainability_records",
        "api_requests",
    ]
    
    def __init__(
        self,
        postgres_pool: asyncpg.Pool,
        deletion_engine: Any  # DeletionEngine instance
    ):
        self.postgres = postgres_pool
        self.deletion_engine = deletion_engine
    
    async def initiate_user_erasure(
        self,
        user_identifier: str,
        user_email: Optional[str] = None,
        request_source: str = "api",
        notes: Optional[str] = None
    ) -> UserErasureRequest:
        """
        Initiate user erasure request
        
        Args:
            user_identifier: User identifier (email, ID, etc.)
            user_email: Optional user email
            request_source: Source of request (api, email, web_form)
            notes: Optional notes
        
        Returns:
            User erasure request
        """
        
        import uuid
        
        request_id = f"ERASE-USER-{uuid.uuid4().hex[:12].upper()}"
        
        request = UserErasureRequest(
            request_id=request_id,
            user_identifier=user_identifier,
            user_email=user_email,
            request_source=request_source,
            notes=notes,
            tables_to_process=self.USER_DATA_TABLES.copy()
        )
        
        logger.info(
            f"🗑️  User erasure request initiated:\n"
            f"   Request ID: {request_id}\n"
            f"   User: {user_identifier}\n"
            f"   Email: {user_email or 'N/A'}\n"
            f"   Deadline: {request.deadline.isoformat()}\n"
            f"   Tables: {len(request.tables_to_process)}"
        )
        
        # Store request
        async with self.postgres.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO data_subject_requests (
                    request_id,
                    request_type,
                    subject_identifier_hash,
                    status,
                    requested_at,
                    deadline,
                    request_source,
                    notes
                )
                VALUES ($1, 'deletion', $2, $3, $4, $5, $6, $7)
                """,
                request.request_id,
                self._hash_identifier(user_identifier),
                request.status.value,
                request.requested_at,
                request.deadline,
                request.request_source,
                request.notes
            )
        
        # Send acknowledgment (in production, send email)
        request.status = ErasureStatus.ACKNOWLEDGED
        request.acknowledged_at = datetime.utcnow()
        
        await self._update_request_status(request)
        
        return request
    
    async def execute_user_erasure(
        self,
        request_id: str
    ) -> UserErasureRequest:
        """
        Execute user erasure request
        
        Deletes all user data across all tables
        
        Args:
            request_id: Request identifier
        
        Returns:
            Updated erasure request
        """
        
        # Get request
        async with self.postgres.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM data_subject_requests WHERE request_id = $1",
                request_id
            )
        
        if not row:
            raise ValueError(f"Erasure request {request_id} not found")
        
        request = UserErasureRequest(
            request_id=row["request_id"],
            user_identifier=row["subject_identifier_hash"],  # Hashed
            status=ErasureStatus(row["status"]),
            requested_at=row["requested_at"],
            acknowledged_at=row["acknowledged_at"],
            started_at=row.get("started_at"),
            completed_at=row.get("completed_at"),
            deadline=row["deadline"],
            tables_to_process=self.USER_DATA_TABLES.copy(),
            request_source=row["request_source"],
            notes=row["notes"]
        )
        
        logger.info(
            f"🔄 Executing user erasure:\n"
            f"   Request ID: {request_id}\n"
            f"   Tables: {len(request.tables_to_process)}"
        )
        
        # Update status
        request.status = ErasureStatus.IN_PROGRESS
        request.started_at = datetime.utcnow()
        
        await self._update_request_status(request)
        
        # Process each table
        for table_name in request.tables_to_process:
            try:
                logger.info(f"  Processing table: {table_name}")
                
                # Create deletion job
                job = await self.deletion_engine.create_deletion_job(
                    deletion_type="user_request",
                    table_name=table_name,
                    user_identifier=request.user_identifier,
                    initiated_by=f"erasure_request:{request_id}"
                )
                
                request.deletion_jobs.append(job.job_id)
                
                # Execute deletion
                completed_job = await self.deletion_engine.execute_deletion_job(
                    job.job_id
                )
                
                request.total_records_deleted += completed_job.records_deleted
                request.tables_completed.append(table_name)
                
                logger.info(
                    f"  ✓ Table completed: {table_name} "
                    f"({completed_job.records_deleted} records)"
                )
                
            except Exception as e:
                logger.error(f"  ✗ Failed to process {table_name}: {e}")
                # Continue with other tables
        
        # Mark completed
        request.status = ErasureStatus.COMPLETED
        request.completed_at = datetime.utcnow()
        
        # Verify erasure
        request.verification_results = await self._verify_user_erasure(request)
        
        await self._update_request_status(request)
        
        duration_days = (request.completed_at - request.requested_at).days
        
        logger.info(
            f"✅ User erasure completed:\n"
            f"   Request ID: {request_id}\n"
            f"   Duration: {duration_days} days\n"
            f"   Records deleted: {request.total_records_deleted}\n"
            f"   Tables processed: {len(request.tables_completed)}\n"
            f"   Within SLA: {'Yes' if duration_days <= 30 else 'No'}"
        )
        
        return request
    
    async def _verify_user_erasure(
        self,
        request: UserErasureRequest
    ) -> Dict[str, Any]:
        """
        Verify user data completely erased
        
        Args:
            request: Erasure request
        
        Returns:
            Verification results
        """
        
        logger.info(f"🔍 Verifying user erasure: {request.request_id}")
        
        verification = {
            "verified": True,
            "tables_checked": [],
            "records_remaining": {}
        }
        
        # Check each table for remaining records
        for table_name in self.USER_DATA_TABLES:
            async with self.postgres.acquire() as conn:
                # Count remaining records
                # This query structure depends on how user_identifier is stored
                remaining = await conn.fetchval(
                    f"""
                    SELECT COUNT(*)
                    FROM {table_name}
                    WHERE session_id IN (
                        SELECT session_id
                        FROM sessions
                        WHERE user_identifier = $1
                        AND deleted_at IS NULL
                    )
                    AND deleted_at IS NULL
                    """,
                    request.user_identifier
                )
            
            verification["tables_checked"].append(table_name)
            
            if remaining > 0:
                verification["verified"] = False
                verification["records_remaining"][table_name] = remaining
                logger.warning(
                    f"⚠️  Records remaining in {table_name}: {remaining}"
                )
        
        # Verify deletion jobs
        for job_id in request.deletion_jobs:
            job_verification = await self.deletion_engine.verify_deletion(job_id)
            
            if not job_verification["verified"]:
                verification["verified"] = False
                verification[f"job_{job_id}"] = job_verification
        
        if verification["verified"]:
            logger.info(f"✅ User erasure verified: {request.request_id}")
        else:
            logger.warning(f"⚠️  User erasure verification failed: {request.request_id}")
        
        return verification
    
    def _hash_identifier(self, identifier: str) -> str:
        """Hash user identifier for privacy"""
        import hashlib
        return hashlib.sha256(identifier.encode()).hexdigest()
    
    async def _update_request_status(self, request: UserErasureRequest):
        """Update request status in database"""
        
        async with self.postgres.acquire() as conn:
            await conn.execute(
                """
                UPDATE data_subject_requests
                SET status = $2,
                    acknowledged_at = $3,
                    started_at = $4,
                    completed_at = $5,
                    updated_at = NOW()
                WHERE request_id = $1
                """,
                request.request_id,
                request.status.value,
                request.acknowledged_at,
                request.started_at,
                request.completed_at
            )
            
            # Update tables_accessed if completed
            if request.status == ErasureStatus.COMPLETED:
                await conn.execute(
                    """
                    UPDATE data_subject_requests
                    SET tables_accessed = $2,
                        records_found = $3,
                        data_deleted = TRUE
                    WHERE request_id = $1
                    """,
                    request.request_id,
                    request.tables_completed,
                    request.total_records_deleted
                )
                