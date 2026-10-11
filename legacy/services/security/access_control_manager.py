"""
Access Control Manager
Least privilege enforcement with quarterly reviews

Acceptance Criteria:
- Quarterly access review complete
- No broad wildcard storage access in production roles
"""

import asyncpg
from typing import Dict, Any, List, Optional, Set
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
import json
import logging

logger = logging.getLogger(__name__)


class Permission(str, Enum):
    """Granular permissions"""
    # Read permissions
    READ_SESSIONS = "read:sessions"
    READ_VERIFICATIONS = "read:verifications"
    READ_RISK = "read:risk"
    READ_EXPLAINABILITY = "read:explainability"
    READ_AUDIT = "read:audit"
    
    # Write permissions
    WRITE_SESSIONS = "write:sessions"
    WRITE_VERIFICATIONS = "write:verifications"
    WRITE_RISK = "write:risk"
    
    # Admin permissions
    MANAGE_USERS = "manage:users"
    MANAGE_ROLES = "manage:roles"
    MANAGE_KEYS = "manage:keys"
    
    # Data privacy permissions
    DELETE_USER_DATA = "delete:user_data"
    EXPORT_USER_DATA = "export:user_data"
    
    # Storage permissions (SPECIFIC, NO WILDCARDS)
    READ_VIDEO_SPECIFIC = "read:video:specific"  # Can read specific video by ID
    WRITE_VIDEO_SPECIFIC = "write:video:specific"  # Can write specific video
    DELETE_VIDEO_SPECIFIC = "delete:video:specific"  # Can delete specific video
    
    # FORBIDDEN PERMISSIONS (will raise error if used)
    # READ_VIDEO_ALL = "read:video:*"  # ❌ WILDCARD NOT ALLOWED
    # WRITE_VIDEO_ALL = "write:video:*"  # ❌ WILDCARD NOT ALLOWED


class Role(str, Enum):
    """Predefined roles with least privilege"""
    VIEWER = "viewer"
    OPERATOR = "operator"
    ANALYST = "analyst"
    ADMIN = "admin"
    DPO = "dpo"  # Data Protection Officer


@dataclass
class RoleDefinition:
    """Role definition with permissions"""
    role: Role
    description: str
    permissions: Set[Permission]
    
    # Review requirements
    requires_quarterly_review: bool = True
    requires_manager_approval: bool = True
    max_duration_days: Optional[int] = None  # Auto-expire after N days


@dataclass
class UserAccess:
    """User access record"""
    user_id: str
    user_email: str
    role: Role
    permissions: Set[Permission]
    
    # Assignment details
    granted_by: str
    granted_at: datetime
    expires_at: Optional[datetime] = None
    
    # Review tracking
    last_reviewed: Optional[datetime] = None
    reviewed_by: Optional[str] = None
    next_review_due: Optional[datetime] = None
    
    # Justification
    business_justification: str = ""
    
    # Status
    active: bool = True


class AccessControlManager:
    """
    Access Control Manager
    
    Features:
    - Least privilege enforcement
    - NO wildcard storage access
    - Quarterly access reviews
    - Automatic expiration
    - Audit trail
    
    Acceptance Criteria:
    - Quarterly reviews enforced
    - No wildcards in production
    """
    
    # Role definitions (least privilege)
    ROLE_DEFINITIONS = {
        Role.VIEWER: RoleDefinition(
            role=Role.VIEWER,
            description="Read-only access to verification results",
            permissions={
                Permission.READ_SESSIONS,
                Permission.READ_VERIFICATIONS
            },
            requires_quarterly_review=True,
            max_duration_days=90
        ),
        
        Role.OPERATOR: RoleDefinition(
            role=Role.OPERATOR,
            description="Process verifications and view results",
            permissions={
                Permission.READ_SESSIONS,
                Permission.READ_VERIFICATIONS,
                Permission.WRITE_VERIFICATIONS,
                Permission.READ_VIDEO_SPECIFIC,  # Can read specific videos only
            },
            requires_quarterly_review=True,
            max_duration_days=180
        ),
        
        Role.ANALYST: RoleDefinition(
            role=Role.ANALYST,
            description="Analyze verification data for improvements",
            permissions={
                Permission.READ_SESSIONS,
                Permission.READ_VERIFICATIONS,
                Permission.READ_RISK,
                Permission.READ_EXPLAINABILITY,
                Permission.READ_AUDIT
            },
            requires_quarterly_review=True,
            max_duration_days=365
        ),
        
        Role.ADMIN: RoleDefinition(
            role=Role.ADMIN,
            description="Full system administration",
            permissions={
                Permission.READ_SESSIONS,
                Permission.READ_VERIFICATIONS,
                Permission.READ_RISK,
                Permission.READ_EXPLAINABILITY,
                Permission.READ_AUDIT,
                Permission.WRITE_SESSIONS,
                Permission.WRITE_VERIFICATIONS,
                Permission.WRITE_RISK,
                Permission.MANAGE_USERS,
                Permission.MANAGE_ROLES,
                Permission.READ_VIDEO_SPECIFIC,
                Permission.WRITE_VIDEO_SPECIFIC,
                Permission.DELETE_VIDEO_SPECIFIC
            },
            requires_quarterly_review=True,
            requires_manager_approval=True,
            max_duration_days=365
        ),
        
        Role.DPO: RoleDefinition(
            role=Role.DPO,
            description="Data Protection Officer - privacy and compliance",
            permissions={
                Permission.READ_SESSIONS,
                Permission.READ_VERIFICATIONS,
                Permission.READ_AUDIT,
                Permission.DELETE_USER_DATA,
                Permission.EXPORT_USER_DATA,
                Permission.READ_VIDEO_SPECIFIC
            },
            requires_quarterly_review=True,
            requires_manager_approval=True
        )
    }
    
    def __init__(self, postgres_pool: asyncpg.Pool):
        self.postgres = postgres_pool
    
    async def grant_access(
        self,
        user_id: str,
        user_email: str,
        role: Role,
        granted_by: str,
        business_justification: str,
        duration_days: Optional[int] = None
    ) -> UserAccess:
        """
        Grant access to user
        
        Args:
            user_id: User identifier
            user_email: User email
            role: Role to grant
            granted_by: Who granted access
            business_justification: Why access is needed
            duration_days: Optional duration (auto-expire)
        
        Returns:
            User access record
        """
        
        # Validate wildcard permissions
        role_def = self.ROLE_DEFINITIONS[role]
        
        for permission in role_def.permissions:
            if "*" in permission.value or "all" in permission.value.lower():
                raise ValueError(
                    f"❌ WILDCARD PERMISSION DETECTED: {permission.value}\n"
                    f"Wildcard permissions are FORBIDDEN in production.\n"
                    f"Use specific permissions instead."
                )
        
        # Calculate expiration
        granted_at = datetime.utcnow()
        
        if duration_days:
            expires_at = granted_at + timedelta(days=duration_days)
        elif role_def.max_duration_days:
            expires_at = granted_at + timedelta(days=role_def.max_duration_days)
        else:
            expires_at = None
        
        # Calculate next review (quarterly = 90 days)
        next_review_due = granted_at + timedelta(days=90)
        
        user_access = UserAccess(
            user_id=user_id,
            user_email=user_email,
            role=role,
            permissions=role_def.permissions,
            granted_by=granted_by,
            granted_at=granted_at,
            expires_at=expires_at,
            next_review_due=next_review_due,
            business_justification=business_justification
        )
        
        # Store in database
        async with self.postgres.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO user_access (
                    user_id,
                    user_email,
                    role,
                    permissions,
                    granted_by,
                    granted_at,
                    expires_at,
                    next_review_due,
                    business_justification,
                    active
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                """,
                user_access.user_id,
                user_access.user_email,
                user_access.role.value,
                [p.value for p in user_access.permissions],
                user_access.granted_by,
                user_access.granted_at,
                user_access.expires_at,
                user_access.next_review_due,
                user_access.business_justification,
                user_access.active
            )
        
        logger.info(
            f"✅ Access granted:\n"
            f"   User: {user_email}\n"
            f"   Role: {role.value}\n"
            f"   Granted by: {granted_by}\n"
            f"   Expires: {expires_at.isoformat() if expires_at else 'Never'}\n"
            f"   Next review: {next_review_due.isoformat()}\n"
            f"   Permissions: {len(user_access.permissions)}"
        )
        
        return user_access
    
    async def revoke_access(
        self,
        user_id: str,
        revoked_by: str,
        reason: str
    ):
        """
        Revoke user access
        
        Args:
            user_id: User identifier
            revoked_by: Who revoked access
            reason: Reason for revocation
        """
        
        async with self.postgres.acquire() as conn:
            await conn.execute(
                """
                UPDATE user_access
                SET active = FALSE,
                    revoked_at = NOW(),
                    revoked_by = $2,
                    revocation_reason = $3
                WHERE user_id = $1
                AND active = TRUE
                """,
                user_id,
                revoked_by,
                reason
            )
        
        logger.warning(
            f"🚫 Access revoked:\n"
            f"   User: {user_id}\n"
            f"   Revoked by: {revoked_by}\n"
            f"   Reason: {reason}"
        )
    
    async def check_permission(
        self,
        user_id: str,
        permission: Permission
    ) -> bool:
        """
        Check if user has permission
        
        Args:
            user_id: User identifier
            permission: Permission to check
        
        Returns:
            True if user has permission
        """
        
        async with self.postgres.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT permissions
                FROM user_access
                WHERE user_id = $1
                AND active = TRUE
                AND (expires_at IS NULL OR expires_at > NOW())
                """,
                user_id
            )
        
        if not row:
            return False
        
        user_permissions = {Permission(p) for p in row["permissions"]}
        
        return permission in user_permissions
    
    async def get_users_requiring_review(self) -> List[UserAccess]:
        """
        Get users requiring quarterly review
        
        ACCEPTANCE CRITERIA: Quarterly access review
        
        Returns:
            List of users needing review
        """
        
        async with self.postgres.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT *
                FROM user_access
                WHERE active = TRUE
                AND next_review_due <= NOW()
                ORDER BY next_review_due ASC
                """
            )
        
        users = []
        
        for row in rows:
            users.append(UserAccess(
                user_id=row["user_id"],
                user_email=row["user_email"],
                role=Role(row["role"]),
                permissions={Permission(p) for p in row["permissions"]},
                granted_by=row["granted_by"],
                granted_at=row["granted_at"],
                expires_at=row["expires_at"],
                last_reviewed=row["last_reviewed"],
                reviewed_by=row["reviewed_by"],
                next_review_due=row["next_review_due"],
                business_justification=row["business_justification"],
                active=row["active"]
            ))
        
        logger.info(
            f"📋 Users requiring review: {len(users)}\n"
            f"   Overdue: {len([u for u in users if u.next_review_due < datetime.utcnow()])}"
        )
        
        return users
    
    async def complete_access_review(
        self,
        user_id: str,
        reviewed_by: str,
        decision: str,  # "approved", "revoked", "modified"
        notes: Optional[str] = None
    ):
        """
        Complete quarterly access review
        
        Args:
            user_id: User identifier
            reviewed_by: Who performed review
            decision: Review decision
            notes: Optional review notes
        """
        
        if decision not in ["approved", "revoked", "modified"]:
            raise ValueError("Invalid decision. Must be: approved, revoked, or modified")
        
        reviewed_at = datetime.utcnow()
        
        if decision == "approved":
            # Approve and schedule next review (90 days)
            next_review_due = reviewed_at + timedelta(days=90)
            
            async with self.postgres.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE user_access
                    SET last_reviewed = $2,
                        reviewed_by = $3,
                        next_review_due = $4,
                        review_notes = $5
                    WHERE user_id = $1
                    AND active = TRUE
                    """,
                    user_id,
                    reviewed_at,
                    reviewed_by,
                    next_review_due,
                    notes
                )
            
            logger.info(
                f"✅ Access review completed (APPROVED):\n"
                f"   User: {user_id}\n"
                f"   Reviewed by: {reviewed_by}\n"
                f"   Next review: {next_review_due.isoformat()}"
            )
            
        elif decision == "revoked":
            # Revoke access
            await self.revoke_access(
                user_id=user_id,
                revoked_by=reviewed_by,
                reason=f"Access review: {notes or 'No longer needed'}"
            )
            
            logger.warning(
                f"🚫 Access review completed (REVOKED):\n"
                f"   User: {user_id}\n"
                f"   Reviewed by: {reviewed_by}"
            )
        
        # Log review
        async with self.postgres.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO access_reviews (
                    user_id,
                    reviewed_by,
                    reviewed_at,
                    decision,
                    notes
                )
                VALUES ($1, $2, $3, $4, $5)
                """,
                user_id,
                reviewed_by,
                reviewed_at,
                decision,
                notes
            )
    
    async def validate_no_wildcards(self) -> Dict[str, Any]:
        """
        Validate no wildcard storage access in production
        
        ACCEPTANCE CRITERIA: No wildcard storage access
        
        Returns:
            Validation report
        """
        
        logger.info("🔍 Validating: No wildcard storage access...")
        
        violations = []
        
        # Check all active users
        async with self.postgres.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT user_id, user_email, role, permissions
                FROM user_access
                WHERE active = TRUE
                """
            )
        
        for row in rows:
            permissions = row["permissions"]
            
            # Check for wildcards
            wildcard_permissions = [
                p for p in permissions
                if "*" in p or "all" in p.lower()
            ]
            
            if wildcard_permissions:
                violations.append({
                    "user_id": row["user_id"],
                    "user_email": row["user_email"],
                    "role": row["role"],
                    "wildcard_permissions": wildcard_permissions
                })
        
        report = {
            "validated_at": datetime.utcnow().isoformat(),
            "total_users_checked": len(rows),
            "violations_found": len(violations),
            "violations": violations,
            "compliant": len(violations) == 0
        }
        
        if violations:
            logger.error(
                f"❌ WILDCARD VIOLATIONS FOUND:\n"
                f"   Users with wildcards: {len(violations)}"
            )
            
            for violation in violations:
                logger.error(
                    f"   - {violation['user_email']}: {', '.join(violation['wildcard_permissions'])}"
                )
        else:
            logger.info("✅ No wildcard storage access found - COMPLIANT")
        
        return report
    
    async def generate_quarterly_review_report(self) -> Dict[str, Any]:
        """
        Generate quarterly access review report
        
        Returns:
            Review report
        """
        
        # Get all active users
        async with self.postgres.acquire() as conn:
            total_users = await conn.fetchval(
                "SELECT COUNT(*) FROM user_access WHERE active = TRUE"
            )
            
            # Users requiring review
            requiring_review = await conn.fetch(
                """
                SELECT user_id, user_email, role, next_review_due
                FROM user_access
                WHERE active = TRUE
                AND next_review_due <= NOW() + INTERVAL '7 days'
                ORDER BY next_review_due ASC
                """
            )
            
            # Recently reviewed
            recently_reviewed = await conn.fetch(
                """
                SELECT user_id, user_email, reviewed_by, reviewed_at, decision
                FROM access_reviews
                WHERE reviewed_at >= NOW() - INTERVAL '90 days'
                ORDER BY reviewed_at DESC
                """
            )
        
        report = {
            "report_date": datetime.utcnow().isoformat(),
            "quarter": f"Q{(datetime.utcnow().month - 1) // 3 + 1} {datetime.utcnow().year}",
            "total_active_users": total_users,
            "requiring_review": {
                "count": len(requiring_review),
                "users": [
                    {
                        "user_id": row["user_id"],
                        "user_email": row["user_email"],
                        "role": row["role"],
                        "review_due": row["next_review_due"].isoformat()
                    }
                    for row in requiring_review
                ]
            },
            "recently_reviewed": {
                "count": len(recently_reviewed),
                "reviews": [
                    {
                        "user_email": row["user_email"],
                        "reviewed_by": row["reviewed_by"],
                        "reviewed_at": row["reviewed_at"].isoformat(),
                        "decision": row["decision"]
                    }
                    for row in recently_reviewed[:10]  # Last 10
                ]
            }
        }
        
        logger.info(
            f"📊 Quarterly Review Report:\n"
            f"   Quarter: {report['quarter']}\n"
            f"   Total users: {total_users}\n"
            f"   Requiring review: {len(requiring_review)}\n"
            f"   Recently reviewed: {len(recently_reviewed)}"
        )
        
        return report