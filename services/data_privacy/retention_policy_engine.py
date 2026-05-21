"""
Retention Policy Engine
Manages configurable retention windows by tenant/jurisdiction
"""

import asyncpg
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class Jurisdiction(str, Enum):
    """Legal jurisdictions with different retention requirements"""
    EU = "eu"                    # GDPR - European Union
    US_CALIFORNIA = "us_ca"      # CCPA - California
    US_OTHER = "us_other"        # Other US states
    UK = "uk"                    # UK GDPR
    CANADA = "canada"            # PIPEDA
    AUSTRALIA = "australia"      # Privacy Act
    JAPAN = "japan"              # APPI
    GLOBAL = "global"            # Default/Global


@dataclass
class RetentionWindow:
    """Retention window configuration"""
    table_name: str
    jurisdiction: Jurisdiction
    tenant_id: Optional[str] = None  # None for global policy
    
    # Retention period
    retention_days: int = 90
    
    # Grace period before hard delete
    grace_period_days: int = 30
    
    # Override settings
    custom_retention: bool = False
    retention_reason: Optional[str] = None
    
    # Compliance
    legal_hold: bool = False
    legal_hold_reason: Optional[str] = None
    
    # Metadata
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    created_by: Optional[str] = None


@dataclass
class DeletionPolicy:
    """Deletion policy for a table"""
    table_name: str
    cascade_tables: List[str] = field(default_factory=list)
    
    # Deletion strategy
    soft_delete: bool = True
    soft_delete_column: str = "deleted_at"
    
    # Audit requirements
    log_deletions: bool = True
    archive_before_delete: bool = False
    archive_location: Optional[str] = None
    
    # Performance
    batch_size: int = 1000
    max_deletions_per_run: int = 10000


class RetentionPolicyEngine:
    """
    Retention Policy Engine
    
    Features:
    - Jurisdiction-specific retention windows
    - Tenant-specific overrides
    - Legal hold support
    - Grace periods before hard deletion
    - Configurable policies per table
    """
    
    # Default retention windows by jurisdiction (days)
    DEFAULT_RETENTION = {
        Jurisdiction.EU: 90,              # GDPR default
        Jurisdiction.US_CALIFORNIA: 90,   # CCPA default
        Jurisdiction.US_OTHER: 180,       # US general
        Jurisdiction.UK: 90,              # UK GDPR
        Jurisdiction.CANADA: 90,          # PIPEDA
        Jurisdiction.AUSTRALIA: 90,       # Privacy Act
        Jurisdiction.JAPAN: 180,          # APPI
        Jurisdiction.GLOBAL: 90           # Global default
    }
    
    # Table-specific minimum retention (compliance requirements)
    MINIMUM_RETENTION = {
        "explainability_records": 2555,   # 7 years for audit
        "risk_assessments": 2555,         # 7 years for compliance
        "api_requests": 30,               # 30 days for monitoring
        "sessions": 90,                   # 90 days for fraud detection
        "verification_results": 90,       # 90 days for appeals
    }
    
    def __init__(self, postgres_pool: asyncpg.Pool):
        self.postgres = postgres_pool
    
    async def get_retention_window(
        self,
        table_name: str,
        jurisdiction: Jurisdiction,
        tenant_id: Optional[str] = None
    ) -> RetentionWindow:
        """
        Get retention window for table/jurisdiction/tenant
        
        Priority:
        1. Tenant-specific override
        2. Jurisdiction-specific policy
        3. Default retention
        
        Args:
            table_name: Table name
            jurisdiction: Legal jurisdiction
            tenant_id: Optional tenant ID for tenant-specific policy
        
        Returns:
            Retention window configuration
        """
        
        # Try tenant-specific first
        if tenant_id:
            async with self.postgres.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT * FROM retention_policies
                    WHERE table_name = $1
                    AND jurisdiction = $2
                    AND tenant_id = $3
                    AND (legal_hold = FALSE OR legal_hold IS NULL)
                    """,
                    table_name,
                    jurisdiction.value,
                    tenant_id
                )
                
                if row:
                    return RetentionWindow(
                        table_name=row["table_name"],
                        jurisdiction=Jurisdiction(row["jurisdiction"]),
                        tenant_id=row["tenant_id"],
                        retention_days=row["retention_days"],
                        grace_period_days=row["grace_period_days"],
                        custom_retention=row["custom_retention"],
                        retention_reason=row["retention_reason"],
                        legal_hold=row["legal_hold"],
                        legal_hold_reason=row["legal_hold_reason"],
                        created_at=row["created_at"],
                        updated_at=row["updated_at"],
                        created_by=row["created_by"]
                    )
        
        # Try jurisdiction-specific
        async with self.postgres.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT * FROM retention_policies
                WHERE table_name = $1
                AND jurisdiction = $2
                AND tenant_id IS NULL
                AND (legal_hold = FALSE OR legal_hold IS NULL)
                """,
                table_name,
                jurisdiction.value
            )
            
            if row:
                return RetentionWindow(
                    table_name=row["table_name"],
                    jurisdiction=Jurisdiction(row["jurisdiction"]),
                    tenant_id=None,
                    retention_days=row["retention_days"],
                    grace_period_days=row["grace_period_days"],
                    custom_retention=row["custom_retention"],
                    retention_reason=row["retention_reason"],
                    legal_hold=row["legal_hold"],
                    legal_hold_reason=row["legal_hold_reason"],
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                    created_by=row["created_by"]
                )
        
        # Use default
        default_retention = self.DEFAULT_RETENTION.get(
            jurisdiction,
            self.DEFAULT_RETENTION[Jurisdiction.GLOBAL]
        )
        
        # Check minimum retention requirements
        minimum_retention = self.MINIMUM_RETENTION.get(table_name, 0)
        retention_days = max(default_retention, minimum_retention)
        
        return RetentionWindow(
            table_name=table_name,
            jurisdiction=jurisdiction,
            tenant_id=tenant_id,
            retention_days=retention_days,
            grace_period_days=30
        )
    
    async def set_retention_policy(
        self,
        table_name: str,
        jurisdiction: Jurisdiction,
        retention_days: int,
        tenant_id: Optional[str] = None,
        grace_period_days: int = 30,
        created_by: Optional[str] = None
    ) -> RetentionWindow:
        """
        Set custom retention policy
        
        Args:
            table_name: Table name
            jurisdiction: Legal jurisdiction
            retention_days: Retention period in days
            tenant_id: Optional tenant ID
            grace_period_days: Grace period before hard delete
            created_by: User who created the policy
        
        Returns:
            Created retention window
        """
        
        # Validate minimum retention
        minimum_retention = self.MINIMUM_RETENTION.get(table_name, 0)
        
        if retention_days < minimum_retention:
            raise ValueError(
                f"Retention period {retention_days} days is below minimum "
                f"{minimum_retention} days for table {table_name}"
            )
        
        logger.info(
            f"📋 Setting retention policy:\n"
            f"   Table: {table_name}\n"
            f"   Jurisdiction: {jurisdiction.value}\n"
            f"   Tenant: {tenant_id or 'global'}\n"
            f"   Retention: {retention_days} days\n"
            f"   Grace Period: {grace_period_days} days"
        )
        
        async with self.postgres.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO retention_policies (
                    table_name,
                    jurisdiction,
                    tenant_id,
                    retention_days,
                    grace_period_days,
                    custom_retention,
                    created_by
                )
                VALUES ($1, $2, $3, $4, $5, TRUE, $6)
                ON CONFLICT (table_name, jurisdiction, COALESCE(tenant_id, ''))
                DO UPDATE SET
                    retention_days = EXCLUDED.retention_days,
                    grace_period_days = EXCLUDED.grace_period_days,
                    custom_retention = TRUE,
                    updated_at = NOW(),
                    created_by = EXCLUDED.created_by
                """,
                table_name,
                jurisdiction.value,
                tenant_id,
                retention_days,
                grace_period_days,
                created_by
            )
        
        return await self.get_retention_window(table_name, jurisdiction, tenant_id)
    
    async def set_legal_hold(
        self,
        table_name: str,
        jurisdiction: Jurisdiction,
        tenant_id: Optional[str],
        reason: str,
        created_by: str
    ):
        """
        Place legal hold on data (prevent deletion)
        
        Args:
            table_name: Table name
            jurisdiction: Legal jurisdiction
            tenant_id: Tenant ID
            reason: Reason for legal hold
            created_by: User placing hold
        """
        
        logger.warning(
            f"⚖️  Legal hold placed:\n"
            f"   Table: {table_name}\n"
            f"   Jurisdiction: {jurisdiction.value}\n"
            f"   Tenant: {tenant_id or 'global'}\n"
            f"   Reason: {reason}\n"
            f"   By: {created_by}"
        )
        
        async with self.postgres.acquire() as conn:
            await conn.execute(
                """
                UPDATE retention_policies
                SET legal_hold = TRUE,
                    legal_hold_reason = $4,
                    updated_at = NOW()
                WHERE table_name = $1
                AND jurisdiction = $2
                AND (tenant_id = $3 OR (tenant_id IS NULL AND $3 IS NULL))
                """,
                table_name,
                jurisdiction.value,
                tenant_id,
                reason
            )
    
    async def release_legal_hold(
        self,
        table_name: str,
        jurisdiction: Jurisdiction,
        tenant_id: Optional[str],
        released_by: str
    ):
        """
        Release legal hold
        
        Args:
            table_name: Table name
            jurisdiction: Legal jurisdiction
            tenant_id: Tenant ID
            released_by: User releasing hold
        """
        
        logger.info(
            f"⚖️  Legal hold released:\n"
            f"   Table: {table_name}\n"
            f"   Jurisdiction: {jurisdiction.value}\n"
            f"   Tenant: {tenant_id or 'global'}\n"
            f"   By: {released_by}"
        )
        
        async with self.postgres.acquire() as conn:
            await conn.execute(
                """
                UPDATE retention_policies
                SET legal_hold = FALSE,
                    legal_hold_reason = NULL,
                    updated_at = NOW()
                WHERE table_name = $1
                AND jurisdiction = $2
                AND (tenant_id = $3 OR (tenant_id IS NULL AND $3 IS NULL))
                """,
                table_name,
                jurisdiction.value,
                tenant_id
            )
    
    async def get_tables_for_deletion(
        self,
        jurisdiction: Jurisdiction,
        tenant_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Get tables with records ready for deletion
        
        Args:
            jurisdiction: Legal jurisdiction
            tenant_id: Optional tenant ID
        
        Returns:
            List of tables with deletion candidates
        """
        
        tables = []
        
        # Get all tables with retention policies
        async with self.postgres.acquire() as conn:
            policies = await conn.fetch(
                """
                SELECT DISTINCT table_name
                FROM retention_policies
                WHERE jurisdiction = $1
                AND (tenant_id = $2 OR tenant_id IS NULL)
                AND legal_hold = FALSE
                """,
                jurisdiction.value,
                tenant_id
            )
        
        for policy in policies:
            table_name = policy["table_name"]
            
            # Get retention window
            window = await self.get_retention_window(
                table_name,
                jurisdiction,
                tenant_id
            )
            
            # Calculate cutoff date
            cutoff_date = datetime.utcnow() - timedelta(days=window.retention_days)
            
            # Count records ready for deletion
            async with self.postgres.acquire() as conn:
                count = await conn.fetchval(
                    f"""
                    SELECT COUNT(*)
                    FROM {table_name}
                    WHERE created_at < $1
                    AND (deleted_at IS NULL OR deleted_at < $2)
                    """,
                    cutoff_date,
                    datetime.utcnow() - timedelta(days=window.grace_period_days)
                )
            
            if count > 0:
                tables.append({
                    "table_name": table_name,
                    "retention_days": window.retention_days,
                    "cutoff_date": cutoff_date,
                    "records_to_delete": count
                })
        
        return tables