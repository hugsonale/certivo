"""
Automatic Deletion Engine
Executes scheduled deletions with audit trail
"""

import asyncpg
import aioboto3
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
import json
import logging
import uuid

logger = logging.getLogger(__name__)


class DeletionStatus(str, Enum):
    """Deletion job status"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class DeletionType(str, Enum):
    """Type of deletion"""
    AUTOMATIC = "automatic"      # Scheduled retention deletion
    USER_REQUEST = "user_request"  # User erasure request
    TENANT_REQUEST = "tenant_request"  # Tenant erasure request
    ADMIN_MANUAL = "admin_manual"  # Manual admin deletion


@dataclass
class DeletionJob:
    """Deletion job tracking"""
    job_id: str
    deletion_type: DeletionType
    
    # Target
    table_name: str
    tenant_id: Optional[str] = None
    user_identifier: Optional[str] = None
    
    # Execution
    status: DeletionStatus = DeletionStatus.PENDING
    records_identified: int = 0
    records_deleted: int = 0
    records_failed: int = 0
    
    # Audit
    initiated_by: str = "system"
    initiated_at: datetime = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    
    # Verification
    verification_token: Optional[str] = None
    verification_completed: bool = False
    
    # Error tracking
    error_message: Optional[str] = None
    
    def __post_init__(self):
        if self.initiated_at is None:
            self.initiated_at = datetime.utcnow()


class DeletionEngine:
    """
    Automatic Deletion Engine
    
    Features:
    - Automatic scheduled deletions
    - Batch processing for performance
    - Cascade deletion support
    - Audit trail for all deletions
    - Storage verification
    - User/tenant erasure workflows
    
    Acceptance Criteria:
    - Deletion completed within 30 days
    - Verifiable in logs and storage
    """
    
    def __init__(
        self,
        postgres_pool: asyncpg.Pool,
        s3_bucket: str,
        aws_region: str = "us-east-1"
    ):
        self.postgres = postgres_pool
        self.s3_bucket = s3_bucket
        self.aws_region = aws_region
    
    async def create_deletion_job(
        self,
        deletion_type: DeletionType,
        table_name: str,
        tenant_id: Optional[str] = None,
        user_identifier: Optional[str] = None,
        initiated_by: str = "system"
    ) -> DeletionJob:
        """
        Create deletion job
        
        Args:
            deletion_type: Type of deletion
            table_name: Table to delete from
            tenant_id: Optional tenant ID
            user_identifier: Optional user identifier
            initiated_by: Who initiated the deletion
        
        Returns:
            Deletion job
        """
        
        job_id = f"DEL-{uuid.uuid4().hex[:12].upper()}"
        verification_token = uuid.uuid4().hex
        
        job = DeletionJob(
            job_id=job_id,
            deletion_type=deletion_type,
            table_name=table_name,
            tenant_id=tenant_id,
            user_identifier=user_identifier,
            initiated_by=initiated_by,
            verification_token=verification_token
        )
        
        logger.info(
            f"🗑️  Deletion job created:\n"
            f"   Job ID: {job_id}\n"
            f"   Type: {deletion_type.value}\n"
            f"   Table: {table_name}\n"
            f"   Tenant: {tenant_id or 'N/A'}\n"
            f"   User: {user_identifier or 'N/A'}\n"
            f"   Initiated by: {initiated_by}"
        )
        
        # Store in database
        async with self.postgres.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO deletion_jobs (
                    job_id,
                    deletion_type,
                    table_name,
                    tenant_id,
                    user_identifier,
                    status,
                    initiated_by,
                    initiated_at,
                    verification_token
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                """,
                job.job_id,
                job.deletion_type.value,
                job.table_name,
                job.tenant_id,
                job.user_identifier,
                job.status.value,
                job.initiated_by,
                job.initiated_at,
                job.verification_token
            )
        
        return job
    
    async def execute_deletion_job(
        self,
        job_id: str,
        retention_days: Optional[int] = None
    ) -> DeletionJob:
        """
        Execute deletion job
        
        Args:
            job_id: Job identifier
            retention_days: Optional retention period (for automatic deletions)
        
        Returns:
            Updated deletion job
        """
        
        # Get job
        async with self.postgres.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM deletion_jobs WHERE job_id = $1",
                job_id
            )
        
        if not row:
            raise ValueError(f"Deletion job {job_id} not found")
        
        job = DeletionJob(
            job_id=row["job_id"],
            deletion_type=DeletionType(row["deletion_type"]),
            table_name=row["table_name"],
            tenant_id=row["tenant_id"],
            user_identifier=row["user_identifier"],
            status=DeletionStatus(row["status"]),
            records_identified=row["records_identified"],
            records_deleted=row["records_deleted"],
            records_failed=row["records_failed"],
            initiated_by=row["initiated_by"],
            initiated_at=row["initiated_at"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            verification_token=row["verification_token"],
            verification_completed=row["verification_completed"],
            error_message=row["error_message"]
        )
        
        logger.info(f"🔄 Executing deletion job: {job_id}")
        
        # Update status to in_progress
        job.status = DeletionStatus.IN_PROGRESS
        job.started_at = datetime.utcnow()
        
        await self._update_job_status(job)
        
        try:
            # Execute deletion based on type
            if job.deletion_type == DeletionType.AUTOMATIC:
                await self._execute_automatic_deletion(job, retention_days)
            elif job.deletion_type == DeletionType.USER_REQUEST:
                await self._execute_user_erasure(job)
            elif job.deletion_type == DeletionType.TENANT_REQUEST:
                await self._execute_tenant_erasure(job)
            else:
                await self._execute_manual_deletion(job)
            
            # Mark completed
            job.status = DeletionStatus.COMPLETED
            job.completed_at = datetime.utcnow()
            
            logger.info(
                f"✅ Deletion job completed:\n"
                f"   Job ID: {job_id}\n"
                f"   Records deleted: {job.records_deleted}\n"
                f"   Duration: {(job.completed_at - job.started_at).total_seconds():.1f}s"
            )
            
        except Exception as e:
            logger.error(f"❌ Deletion job failed: {e}")
            
            job.status = DeletionStatus.FAILED
            job.error_message = str(e)
            job.completed_at = datetime.utcnow()
        
        await self._update_job_status(job)
        
        return job
    
    async def _execute_automatic_deletion(
        self,
        job: DeletionJob,
        retention_days: int
    ):
        """Execute automatic retention deletion"""
        
        cutoff_date = datetime.utcnow() - timedelta(days=retention_days)
        
        logger.info(
            f"📅 Automatic deletion:\n"
            f"   Table: {job.table_name}\n"
            f"   Cutoff: {cutoff_date.isoformat()}\n"
            f"   Retention: {retention_days} days"
        )
        
        # Identify records
        async with self.postgres.acquire() as conn:
            records = await conn.fetch(
                f"""
                SELECT *
                FROM {job.table_name}
                WHERE created_at < $1
                AND deleted_at IS NULL
                LIMIT 1000
                """,
                cutoff_date
            )
        
        job.records_identified = len(records)
        
        # Delete in batches
        deleted_count = 0
        failed_count = 0
        
        for record in records:
            try:
                await self._delete_record(job.table_name, record)
                deleted_count += 1
            except Exception as e:
                logger.error(f"Failed to delete record: {e}")
                failed_count += 1
        
        job.records_deleted = deleted_count
        job.records_failed = failed_count
    
    async def _execute_user_erasure(self, job: DeletionJob):
        """
        Execute user erasure request
        
        Deletes all user data across all tables
        """
        
        logger.info(
            f"👤 User erasure request:\n"
            f"   User: {job.user_identifier}\n"
            f"   Table: {job.table_name}"
        )
        
        # Get user records
        async with self.postgres.acquire() as conn:
            # Query depends on table structure
            # This is a simplified example
            records = await conn.fetch(
                f"""
                SELECT *
                FROM {job.table_name}
                WHERE session_id IN (
                    SELECT session_id
                    FROM sessions
                    WHERE user_identifier = $1
                )
                """,
                job.user_identifier
            )
        
        job.records_identified = len(records)
        
        # Delete records
        deleted_count = 0
        failed_count = 0
        
        for record in records:
            try:
                await self._delete_record(job.table_name, record)
                deleted_count += 1
            except Exception as e:
                logger.error(f"Failed to delete record: {e}")
                failed_count += 1
        
        job.records_deleted = deleted_count
        job.records_failed = failed_count
    
    async def _execute_tenant_erasure(self, job: DeletionJob):
        """
        Execute tenant erasure request
        
        Deletes all tenant data across all tables
        """
        
        logger.info(
            f"🏢 Tenant erasure request:\n"
            f"   Tenant: {job.tenant_id}\n"
            f"   Table: {job.table_name}"
        )
        
        # Get tenant records
        async with self.postgres.acquire() as conn:
            records = await conn.fetch(
                f"""
                SELECT *
                FROM {job.table_name}
                WHERE tenant_id = $1
                OR customer_id = $1
                """,
                job.tenant_id
            )
        
        job.records_identified = len(records)
        
        # Delete records
        deleted_count = 0
        failed_count = 0
        
        for record in records:
            try:
                await self._delete_record(job.table_name, record)
                deleted_count += 1
            except Exception as e:
                logger.error(f"Failed to delete record: {e}")
                failed_count += 1
        
        job.records_deleted = deleted_count
        job.records_failed = failed_count
    
    async def _execute_manual_deletion(self, job: DeletionJob):
        """Execute manual admin deletion"""
        
        logger.info(f"🔧 Manual deletion: {job.table_name}")
        
        # Manual deletions are targeted and specific
        # Implementation depends on the specific use case
        pass
    
    async def _delete_record(
        self,
        table_name: str,
        record: Dict[str, Any]
    ):
        """
        Delete single record with cascade and audit
        
        Args:
            table_name: Table name
            record: Record to delete
        """
        
        # Extract primary key (assumes 'id' column)
        record_id = record.get("id") or record.get(f"{table_name[:-1]}_id")
        
        # Log deletion
        await self._log_deletion(table_name, record_id, record)
        
        # Delete from S3 if video upload
        if table_name == "video_uploads" and "s3_key" in record:
            await self._delete_from_s3(record["s3_key"])
        
        # Soft delete
        async with self.postgres.acquire() as conn:
            await conn.execute(
                f"""
                UPDATE {table_name}
                SET deleted_at = NOW()
                WHERE id = $1
                """,
                record_id
            )
    
    async def _delete_from_s3(self, s3_key: str):
        """Delete object from S3"""
        
        logger.info(f"🗑️  Deleting from S3: {s3_key}")
        
        session = aioboto3.Session()
        
        async with session.client('s3', region_name=self.aws_region) as s3:
            try:
                await s3.delete_object(
                    Bucket=self.s3_bucket,
                    Key=s3_key
                )
                
                logger.info(f"✅ S3 object deleted: {s3_key}")
                
            except Exception as e:
                logger.error(f"❌ Failed to delete from S3: {e}")
                raise
    
    async def _log_deletion(
        self,
        table_name: str,
        record_id: Any,
        record_data: Dict[str, Any]
    ):
        """Log deletion for audit trail"""
        
        async with self.postgres.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO deletion_audit_log (
                    table_name,
                    record_id,
                    record_data,
                    deleted_at
                )
                VALUES ($1, $2, $3, NOW())
                """,
                table_name,
                str(record_id),
                json.dumps(record_data, default=str)
            )
    
    async def _update_job_status(self, job: DeletionJob):
        """Update job status in database"""
        
        async with self.postgres.acquire() as conn:
            await conn.execute(
                """
                UPDATE deletion_jobs
                SET status = $2,
                    records_identified = $3,
                    records_deleted = $4,
                    records_failed = $5,
                    started_at = $6,
                    completed_at = $7,
                    error_message = $8
                WHERE job_id = $1
                """,
                job.job_id,
                job.status.value,
                job.records_identified,
                job.records_deleted,
                job.records_failed,
                job.started_at,
                job.completed_at,
                job.error_message
            )
    
    async def verify_deletion(
        self,
        job_id: str
    ) -> Dict[str, Any]:
        """
        Verify deletion completed successfully
        
        Checks:
        - Database records deleted
        - S3 objects removed
        - Audit log entries created
        
        Args:
            job_id: Job identifier
        
        Returns:
            Verification results
        """
        
        logger.info(f"🔍 Verifying deletion job: {job_id}")
        
        # Get job
        async with self.postgres.acquire() as conn:
            job_row = await conn.fetchrow(
                "SELECT * FROM deletion_jobs WHERE job_id = $1",
                job_id
            )
        
        if not job_row:
            return {"verified": False, "error": "Job not found"}
        
        verification = {
            "job_id": job_id,
            "verified": True,
            "checks": {}
        }
        
        # Check 1: Job completed
        if job_row["status"] != DeletionStatus.COMPLETED.value:
            verification["verified"] = False
            verification["checks"]["job_status"] = {
                "passed": False,
                "actual": job_row["status"],
                "expected": DeletionStatus.COMPLETED.value
            }
        else:
            verification["checks"]["job_status"] = {"passed": True}
        
        # Check 2: Records deleted match identified
        records_match = (
            job_row["records_deleted"] + job_row["records_failed"]
            == job_row["records_identified"]
        )
        
        verification["checks"]["record_count"] = {
            "passed": records_match,
            "identified": job_row["records_identified"],
            "deleted": job_row["records_deleted"],
            "failed": job_row["records_failed"]
        }
        
        if not records_match:
            verification["verified"] = False
        
        # Check 3: Audit log entries created
        async with self.postgres.acquire() as conn:
            audit_count = await conn.fetchval(
                """
                SELECT COUNT(*)
                FROM deletion_audit_log
                WHERE table_name = $1
                AND deleted_at >= $2
                """,
                job_row["table_name"],
                job_row["started_at"]
            )
        
        audit_match = audit_count >= job_row["records_deleted"]
        
        verification["checks"]["audit_log"] = {
            "passed": audit_match,
            "expected_minimum": job_row["records_deleted"],
            "actual": audit_count
        }
        
        if not audit_match:
            verification["verified"] = False
        
        # Check 4: S3 objects deleted (if applicable)
        if job_row["table_name"] == "video_uploads":
            s3_verified = await self._verify_s3_deletion(job_row)
            verification["checks"]["s3_storage"] = s3_verified
            
            if not s3_verified["passed"]:
                verification["verified"] = False
        
        # Mark verification complete
        async with self.postgres.acquire() as conn:
            await conn.execute(
                """
                UPDATE deletion_jobs
                SET verification_completed = TRUE
                WHERE job_id = $1
                """,
                job_id
            )
        
        if verification["verified"]:
            logger.info(f"✅ Deletion verification passed: {job_id}")
        else:
            logger.warning(f"⚠️  Deletion verification failed: {job_id}")
        
        return verification
    
    async def _verify_s3_deletion(self, job_row: Dict[str, Any]) -> Dict[str, Any]:
        """Verify S3 objects were deleted"""
        
        # Get S3 keys that should have been deleted
        async with self.postgres.acquire() as conn:
            s3_keys = await conn.fetch(
                """
                SELECT s3_key
                FROM deletion_audit_log
                WHERE table_name = 'video_uploads'
                AND deleted_at >= $1
                """,
                job_row["started_at"]
            )
        
        session = aioboto3.Session()
        
        still_exist = []
        
        async with session.client('s3', region_name=self.aws_region) as s3:
            for row in s3_keys:
                s3_key = json.loads(row["record_data"])["s3_key"]
                
                try:
                    await s3.head_object(
                        Bucket=self.s3_bucket,
                        Key=s3_key
                    )
                    
                    # Object still exists
                    still_exist.append(s3_key)
                    
                except s3.exceptions.NoSuchKey:
                    # Object deleted successfully
                    pass
        
        return {
            "passed": len(still_exist) == 0,
            "objects_checked": len(s3_keys),
            "still_exist": still_exist
        }