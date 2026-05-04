"""
Immutable Audit Logging System
Write-only append logs for all privileged actions
"""

import hashlib
import json
from typing import Dict, Any, Optional
from datetime import datetime
import asyncpg
from enum import Enum


class AuditAction(str, Enum):
    """Auditable admin actions"""
    
    # Authentication
    LOGIN_SUCCESS = "login_success"
    LOGIN_FAILURE = "login_failure"
    LOGOUT = "logout"
    MFA_ENROLLED = "mfa_enrolled"
    MFA_DISABLED = "mfa_disabled"
    SESSION_CREATED = "session_created"
    SESSION_REVOKED = "session_revoked"
    
    # Authorization
    PERMISSION_GRANTED = "permission_granted"
    PERMISSION_DENIED = "permission_denied"
    ROLE_ASSIGNED = "role_assigned"
    ROLE_REVOKED = "role_revoked"
    
    # Device management
    DEVICE_REVOKED = "device_revoked"
    DEVICE_TRUST_UPDATED = "device_trust_updated"
    
    # Session management
    SESSION_REVOKED_ADMIN = "session_revoked_admin"
    ALL_SESSIONS_REVOKED = "all_sessions_revoked"
    
    # User management
    USER_CREATED = "user_created"
    USER_UPDATED = "user_updated"
    USER_DELETED = "user_deleted"
    USER_PASSWORD_RESET = "user_password_reset"
    USER_MFA_RESET = "user_mfa_reset"
    
    # Configuration changes
    SETTINGS_UPDATED = "settings_updated"
    RATE_LIMIT_UPDATED = "rate_limit_updated"
    THRESHOLD_UPDATED = "threshold_updated"
    SECURITY_RULE_UPDATED = "security_rule_updated"
    
    # Security events
    UNAUTHORIZED_ACCESS_ATTEMPT = "unauthorized_access_attempt"
    PRIVILEGE_ESCALATION_ATTEMPT = "privilege_escalation_attempt"
    SUSPICIOUS_ACTIVITY = "suspicious_activity"


class AuditLogger:
    """
    Immutable audit logging system
    
    Features:
    - Write-only append logs
    - Cryptographic chaining (each log references previous)
    - Tamper detection via hash chain
    - No update or delete operations
    - Permanent retention
    """
    
    def __init__(self, postgres_pool: asyncpg.Pool):
        self.postgres = postgres_pool
    
    async def log_action(
        self,
        action: AuditAction,
        actor_id: str,
        actor_ip: str,
        target_resource: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        result: str = "success"
    ) -> str:
        """
        Log privileged action (immutable)
        
        Args:
            action: Action type
            actor_id: User who performed action
            actor_ip: IP address of actor
            target_resource: Resource affected (e.g., device_id, user_id)
            details: Additional action details
            result: "success" or "failure"
        
        Returns:
            Log entry ID
        """
        
        # Get previous log hash for chaining
        previous_hash = await self._get_last_log_hash()
        
        # Create log entry
        timestamp = datetime.utcnow()
        
        log_data = {
            "action": action.value,
            "actor_id": actor_id,
            "actor_ip_hash": self._hash_ip(actor_ip),
            "target_resource": target_resource,
            "details": json.dumps(details or {}),
            "result": result,
            "timestamp": timestamp.isoformat(),
            "previous_hash": previous_hash
        }
        
        # Calculate hash of this entry
        current_hash = self._calculate_hash(log_data)
        log_data["hash"] = current_hash
        
        # Store in database (append-only)
        async with self.postgres.acquire() as conn:
            log_id = await conn.fetchval(
                """
                INSERT INTO audit_logs
                (action, actor_id, actor_ip_hash, target_resource, details,
                 result, timestamp_utc, previous_hash, hash)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                RETURNING id
                """,
                log_data["action"],
                log_data["actor_id"],
                log_data["actor_ip_hash"],
                log_data["target_resource"],
                log_data["details"],
                log_data["result"],
                timestamp,
                log_data["previous_hash"],
                log_data["hash"]
            )
        
        return str(log_id)
    
    async def verify_integrity(
        self,
        start_id: Optional[int] = None,
        end_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Verify audit log integrity via hash chain
        
        Args:
            start_id: Starting log ID (None = from beginning)
            end_id: Ending log ID (None = to end)
        
        Returns:
            Verification result with any tampered entries
        """
        
        query = """
            SELECT id, action, actor_id, actor_ip_hash, target_resource,
                   details, result, timestamp_utc, previous_hash, hash
            FROM audit_logs
            WHERE 1=1
        """
        
        params = []
        
        if start_id:
            query += " AND id >= $1"
            params.append(start_id)
        
        if end_id:
            query += f" AND id <= ${len(params) + 1}"
            params.append(end_id)
        
        query += " ORDER BY id ASC"
        
        async with self.postgres.acquire() as conn:
            logs = await conn.fetch(query, *params)
        
        if not logs:
            return {
                "valid": True,
                "total_entries": 0,
                "tampered_entries": []
            }
        
        tampered = []
        expected_previous = None
        
        for log in logs:
            log_dict = dict(log)
            
            # Check hash chain
            if expected_previous is not None:
                if log_dict["previous_hash"] != expected_previous:
                    tampered.append({
                        "id": log_dict["id"],
                        "reason": "Hash chain broken",
                        "expected_previous": expected_previous,
                        "actual_previous": log_dict["previous_hash"]
                    })
            
            # Verify hash of this entry
            stored_hash = log_dict.pop("hash")
            calculated_hash = self._calculate_hash(log_dict)
            
            if stored_hash != calculated_hash:
                tampered.append({
                    "id": log_dict["id"],
                    "reason": "Hash mismatch",
                    "expected_hash": calculated_hash,
                    "actual_hash": stored_hash
                })
            
            expected_previous = stored_hash
        
        return {
            "valid": len(tampered) == 0,
            "total_entries": len(logs),
            "tampered_entries": tampered
        }
    
    async def query_logs(
        self,
        actor_id: Optional[str] = None,
        action: Optional[AuditAction] = None,
        target_resource: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 100
    ) -> list[Dict[str, Any]]:
        """
        Query audit logs (read-only)
        
        Returns:
            List of audit log entries
        """
        
        where_clauses = []
        params = []
        param_idx = 1
        
        if actor_id:
            where_clauses.append(f"actor_id = ${param_idx}")
            params.append(actor_id)
            param_idx += 1
        
        if action:
            where_clauses.append(f"action = ${param_idx}")
            params.append(action.value)
            param_idx += 1
        
        if target_resource:
            where_clauses.append(f"target_resource = ${param_idx}")
            params.append(target_resource)
            param_idx += 1
        
        if start_time:
            where_clauses.append(f"timestamp_utc >= ${param_idx}")
            params.append(start_time)
            param_idx += 1
        
        if end_time:
            where_clauses.append(f"timestamp_utc <= ${param_idx}")
            params.append(end_time)
            param_idx += 1
        
        query = "SELECT * FROM audit_logs"
        
        if where_clauses:
            query += " WHERE " + " AND ".join(where_clauses)
        
        query += f" ORDER BY timestamp_utc DESC LIMIT ${param_idx}"
        params.append(limit)
        
        async with self.postgres.acquire() as conn:
            rows = await conn.fetch(query, *params)
        
        return [dict(row) for row in rows]
    
    async def _get_last_log_hash(self) -> Optional[str]:
        """Get hash of most recent log entry"""
        
        async with self.postgres.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT hash FROM audit_logs ORDER BY id DESC LIMIT 1"
            )
        
        return row["hash"] if row else None
    
    def _calculate_hash(self, log_data: Dict[str, Any]) -> str:
        """
        Calculate SHA256 hash of log entry
        
        Includes all fields except 'hash' itself
        """
        
        # Sort keys for consistent hashing
        sorted_keys = sorted(k for k in log_data.keys() if k != "hash")
        
        # Create canonical representation
        canonical = "|".join(
            f"{k}:{log_data[k]}" for k in sorted_keys
        )
        
        return hashlib.sha256(canonical.encode()).hexdigest()
    
    def _hash_ip(self, ip: str) -> str:
        """Hash IP address for privacy"""
        return hashlib.sha256(ip.encode()).hexdigest()[:16]