"""
Tenant Erasure Workflow
Complete tenant data erasure
"""

import asyncpg
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


@dataclass
class TenantErasureRequest:
    """Tenant erasure request tracking"""
    request_id: str
    tenant_id: str
    tenant_name: Optional[str] = None
    
    # Status
    status: str = "received"
    
    # SLA tracking
    requested_at: datetime = None
    completed_at: Optional[datetime] = None
    deadline: datetime = None
    
    # Progress
    tables_to_process: List[str] = None
    tables_completed: List[str] = None
    deletion_jobs: List[str] = None
    
    # Results
    total_records_deleted: int = 0
    
    def __post_init__(self):
        if self.requested_at is None:
            self.requested_at = datetime.utcnow()
        if self.deadline is None:
            self.deadline = self.requested_at + timedelta(days=30)
        if self.tables_completed is None:
            self.tables_completed = []
        if self.deletion_jobs is None:
            self.deletion_jobs = []


class TenantErasureService:
    """
    Tenant Erasure Service
    
    Erases all tenant data when tenant account is closed
    """
    
    # Tables containing tenant data
    TENANT_DATA_TABLES = [
        "sessions",
        "challenges",
        "verification_results",
        "video_uploads",
        "risk_assessments",
        "explainability_records",
        "api_requests",
        "retention_policies",
    ]
    
    def __init__(
        self,
        postgres_pool: asyncpg.Pool,
        deletion_engine: Any
    ):
        self.postgres = postgres_pool
        self.deletion_engine = deletion_engine
    
    async def initiate_tenant_erasure(
        self,
        tenant_id: str,
        tenant_name: Optional[str] = None
    ) -> TenantErasureRequest:
        """
        Initiate tenant erasure request
        
        Args:
            tenant_id: Tenant identifier
            tenant_name: Optional tenant name
        
        Returns:
            Tenant erasure request
        """
        
        import uuid
        
        request_id = f"ERASE-TENANT-{uuid.uuid4().hex[:12].upper()}"
        
        request = TenantErasureRequest(
            request_id=request_id,
            tenant_id=tenant_id,
            tenant_name=tenant_name,
            tables_to_process=self.TENANT_DATA_TABLES.copy()
        )
        
        logger.info(
            f"🗑️  Tenant erasure request initiated:\n"
            f"   Request ID: {request_id}\n"
            f"   Tenant: {tenant_id}\n"
            f"   Name: {tenant_name or 'N/A'}\n"
            f"   Deadline: {request.deadline.isoformat()}"
        )
        
        # Store request (reuse data_subject_requests table)
        async with self.postgres.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO data_subject_requests (
                    request_id,
                    request_type,
                    subject_identifier_hash,
                    status,
                    requested_at,
                    deadline
                )
                VALUES ($1, 'tenant_deletion', $2, $3, $4, $5)
                """,
                request.request_id,
                tenant_id,
                request.status,
                request.requested_at,
                request.deadline
            )
        
        return request
    
    async def execute_tenant_erasure(
        self,
        request_id: str
    ) -> TenantErasureRequest:
        """
        Execute tenant erasure request
        
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
        
        request = TenantErasureRequest(
            request_id=row["request_id"],
            tenant_id=row["subject_identifier_hash"],
            status=row["status"],
            requested_at=row["requested_at"],
            completed_at=row.get("completed_at"),
            deadline=row["deadline"],
            tables_to_process=self.TENANT_DATA_TABLES.copy()
        )
        
        logger.info(f"🔄 Executing tenant erasure: {request_id}")
        
        request.status = "in_progress"
        
        # Process each table
        for table_name in request.tables_to_process:
            try:
                logger.info(f"  Processing table: {table_name}")
                
                # Create deletion job
                job = await self.deletion_engine.create_deletion_job(
                    deletion_type="tenant_request",
                    table_name=table_name,
                    tenant_id=request.tenant_id,
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
        
        # Mark completed
        request.status = "completed"
        request.completed_at = datetime.utcnow()
        
        duration_days = (request.completed_at - request.requested_at).days
        
        logger.info(
            f"✅ Tenant erasure completed:\n"
            f"   Request ID: {request_id}\n"
            f"   Duration: {duration_days} days\n"
            f"   Records deleted: {request.total_records_deleted}"
        )
        
        # Update database
        async with self.postgres.acquire() as conn:
            await conn.execute(
                """
                UPDATE data_subject_requests
                SET status = $2,
                    completed_at = $3,
                    records_found = $4,
                    data_deleted = TRUE
                WHERE request_id = $1
                """,
                request.request_id,
                request.status,
                request.completed_at,
                request.total_records_deleted
            )
        
        return request