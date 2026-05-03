"""
Role-Based Access Control (RBAC)
Hierarchical permission system with least privilege principle
"""

from typing import List, Set, Optional, Dict, Any
from enum import Enum
from dataclasses import dataclass
import redis.asyncio as redis
import asyncpg
from datetime import datetime


class Permission(str, Enum):
    """System permissions (fine-grained)"""
    
    # Read permissions
    VIEW_SESSIONS = "view_sessions"
    VIEW_DEVICES = "view_devices"
    VIEW_CHALLENGES = "view_challenges"
    VIEW_USERS = "view_users"
    VIEW_AUDIT_LOGS = "view_audit_logs"
    VIEW_METRICS = "view_metrics"
    
    # Write permissions
    REVOKE_DEVICE = "revoke_device"
    REVOKE_SESSION = "revoke_session"
    UPDATE_TRUST_LEVEL = "update_trust_level"
    
    # User management
    CREATE_USER = "create_user"
    UPDATE_USER = "update_user"
    DELETE_USER = "delete_user"
    RESET_USER_MFA = "reset_user_mfa"
    
    # System management
    MANAGE_SETTINGS = "manage_settings"
    MANAGE_RATE_LIMITS = "manage_rate_limits"
    MANAGE_THRESHOLDS = "manage_thresholds"
    
    # Security
    VIEW_SECURITY_EVENTS = "view_security_events"
    MANAGE_SECURITY_RULES = "manage_security_rules"
    
    # Super admin
    MANAGE_ROLES = "manage_roles"
    MANAGE_PERMISSIONS = "manage_permissions"


class Role(str, Enum):
    """Predefined roles with permission sets"""
    
    SUPER_ADMIN = "super_admin"
    SECURITY_ADMIN = "security_admin"
    OPERATIONS_ADMIN = "operations_admin"
    ANALYST = "analyst"
    VIEWER = "viewer"


@dataclass
class RoleDefinition:
    """Role with assigned permissions"""
    name: str
    permissions: Set[Permission]
    description: str


# Role hierarchy (permissions inherited from lower roles)
ROLE_DEFINITIONS: Dict[Role, RoleDefinition] = {
    Role.VIEWER: RoleDefinition(
        name="Viewer",
        permissions={
            Permission.VIEW_SESSIONS,
            Permission.VIEW_DEVICES,
            Permission.VIEW_CHALLENGES,
            Permission.VIEW_METRICS
        },
        description="Read-only access to basic data"
    ),
    
    Role.ANALYST: RoleDefinition(
        name="Analyst",
        permissions={
            # Inherit from VIEWER
            Permission.VIEW_SESSIONS,
            Permission.VIEW_DEVICES,
            Permission.VIEW_CHALLENGES,
            Permission.VIEW_METRICS,
            # Additional permissions
            Permission.VIEW_AUDIT_LOGS,
            Permission.VIEW_SECURITY_EVENTS
        },
        description="Analyst with access to logs and security events"
    ),
    
    Role.OPERATIONS_ADMIN: RoleDefinition(
        name="Operations Admin",
        permissions={
            # Inherit from ANALYST
            Permission.VIEW_SESSIONS,
            Permission.VIEW_DEVICES,
            Permission.VIEW_CHALLENGES,
            Permission.VIEW_METRICS,
            Permission.VIEW_AUDIT_LOGS,
            Permission.VIEW_SECURITY_EVENTS,
            # Additional permissions
            Permission.REVOKE_DEVICE,
            Permission.REVOKE_SESSION,
            Permission.UPDATE_TRUST_LEVEL
        },
        description="Operations admin with device/session management"
    ),
    
    Role.SECURITY_ADMIN: RoleDefinition(
        name="Security Admin",
        permissions={
            # Inherit from OPERATIONS_ADMIN
            Permission.VIEW_SESSIONS,
            Permission.VIEW_DEVICES,
            Permission.VIEW_CHALLENGES,
            Permission.VIEW_METRICS,
            Permission.VIEW_AUDIT_LOGS,
            Permission.VIEW_SECURITY_EVENTS,
            Permission.REVOKE_DEVICE,
            Permission.REVOKE_SESSION,
            Permission.UPDATE_TRUST_LEVEL,
            # Additional permissions
            Permission.VIEW_USERS,
            Permission.MANAGE_SECURITY_RULES,
            Permission.MANAGE_RATE_LIMITS,
            Permission.MANAGE_THRESHOLDS
        },
        description="Security admin with security configuration access"
    ),
    
    Role.SUPER_ADMIN: RoleDefinition(
        name="Super Admin",
        permissions=set(Permission),  # All permissions
        description="Super admin with full system access"
    )
}


class RBACManager:
    """Manage role-based access control"""
    
    def __init__(self, redis_client: redis.Redis, postgres_pool: asyncpg.Pool):
        self.redis = redis_client
        self.postgres = postgres_pool
    
    def get_role_permissions(self, role: Role) -> Set[Permission]:
        """Get all permissions for a role"""
        return ROLE_DEFINITIONS[role].permissions
    
    async def assign_role_to_user(
        self,
        user_id: str,
        role: Role,
        assigned_by: str
    ) -> bool:
        """
        Assign role to user
        
        Args:
            user_id: User identifier
            role: Role to assign
            assigned_by: Admin who assigned the role
        
        Returns:
            True if successful
        """
        
        async with self.postgres.acquire() as conn:
            # Store in database
            await conn.execute(
                """
                INSERT INTO user_roles (user_id, role, assigned_by, assigned_at)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (user_id) 
                DO UPDATE SET role = $2, assigned_by = $3, assigned_at = $4
                """,
                user_id,
                role.value,
                assigned_by,
                datetime.utcnow()
            )
            
            # Cache in Redis
            await self.redis.hset(
                f"user_role:{user_id}",
                mapping={
                    "role": role.value,
                    "assigned_at": datetime.utcnow().isoformat()
                }
            )
            await self.redis.expire(f"user_role:{user_id}", 3600)  # 1 hour cache
        
        return True
    
    async def get_user_role(self, user_id: str) -> Optional[Role]:
        """Get user's role"""
        
        # Try cache first
        cached = await self.redis.hget(f"user_role:{user_id}", "role")
        if cached:
            return Role(cached)
        
        # Query database
        async with self.postgres.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT role FROM user_roles WHERE user_id = $1",
                user_id
            )
            
            if row:
                role = Role(row["role"])
                
                # Update cache
                await self.redis.hset(
                    f"user_role:{user_id}",
                    mapping={
                        "role": role.value,
                        "assigned_at": datetime.utcnow().isoformat()
                    }
                )
                await self.redis.expire(f"user_role:{user_id}", 3600)
                
                return role
        
        return None
    
    async def check_permission(
        self,
        user_id: str,
        permission: Permission
    ) -> bool:
        """
        Check if user has specific permission
        
        Args:
            user_id: User identifier
            permission: Permission to check
        
        Returns:
            True if user has permission
        """
        
        role = await self.get_user_role(user_id)
        
        if not role:
            return False
        
        role_permissions = self.get_role_permissions(role)
        
        return permission in role_permissions
    
    async def require_permission(
        self,
        user_id: str,
        permission: Permission
    ):
        """
        Require permission (raises exception if missing)
        
        Raises:
            PermissionDenied
        """
        
        has_permission = await self.check_permission(user_id, permission)
        
        if not has_permission:
            from fastapi import HTTPException
            raise HTTPException(
                status_code=403,
                detail={
                    "error": "Permission denied",
                    "error_code": "INSUFFICIENT_PERMISSIONS",
                    "required_permission": permission.value
                }
            )
    
    async def get_user_permissions(self, user_id: str) -> Set[Permission]:
        """Get all permissions for user"""
        
        role = await self.get_user_role(user_id)
        
        if not role:
            return set()
        
        return self.get_role_permissions(role)