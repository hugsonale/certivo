"""
Finding Tracker with SLA Management
Track security findings with automatic SLA monitoring
"""

import asyncio
import asyncpg
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from dataclasses import dataclass
from enum import Enum
import json
import logging

logger = logging.getLogger(__name__)


class FindingStatus(str, Enum):
    """Finding lifecycle status"""
    OPEN = "open"
    INVESTIGATING = "investigating"
    REMEDIATION = "remediation"
    VERIFICATION = "verification"
    CLOSED = "closed"
    WONT_FIX = "wont_fix"


class SLAStatus(str, Enum):
    """SLA compliance status"""
    ON_TRACK = "on_track"
    AT_RISK = "at_risk"      # < 25% time remaining
    OVERDUE = "overdue"
    BREACHED = "breached"     # > 24h overdue


@dataclass
class FindingSLA:
    """SLA configuration by severity"""
    severity: str
    resolution_hours: int
    escalation_hours: int
    
    @property
    def resolution_timedelta(self) -> timedelta:
        return timedelta(hours=self.resolution_hours)
    
    @property
    def escalation_timedelta(self) -> timedelta:
        return timedelta(hours=self.escalation_hours)


# SLA definitions
SLA_CONFIG = {
    "P0": FindingSLA(severity="P0", resolution_hours=24, escalation_hours=12),
    "P1": FindingSLA(severity="P1", resolution_hours=168, escalation_hours=120),  # 7 days, 5 days
    "P2": FindingSLA(severity="P2", resolution_hours=336, escalation_hours=240),  # 14 days, 10 days
    "P3": FindingSLA(severity="P3", resolution_hours=720, escalation_hours=600)   # 30 days, 25 days
}


class FindingTracker:
    """
    Finding tracker with SLA management
    
    Features:
    - Automatic SLA calculation
    - Escalation alerts
    - Status tracking
    - Remediation verification
    """
    
    def __init__(self, postgres_pool: asyncpg.Pool):
        self.postgres = postgres_pool
    
    async def create_finding(
        self,
        finding_id: str,
        title: str,
        severity: str,
        attack_type: str,
        description: str,
        impact: str,
        reproduction_steps: List[str],
        affected_components: List[str],
        bypass_rate: float,
        discovered_by: str = "automated_red_team"
    ) -> str:
        """
        Create new security finding
        
        Args:
            finding_id: Unique identifier (e.g., RT-20250115-001)
            title: Short descriptive title
            severity: P0, P1, P2, or P3
            attack_type: Type of attack
            description: Detailed description
            impact: Business/security impact
            reproduction_steps: List of steps to reproduce
            affected_components: List of affected components
            bypass_rate: Attack success rate (0.0 - 1.0)
            discovered_by: Who/what discovered the finding
        
        Returns:
            Finding ID
        """
        
        # Calculate SLA deadline
        sla = SLA_CONFIG.get(severity)
        if not sla:
            raise ValueError(f"Invalid severity: {severity}")
        
        discovered_at = datetime.utcnow()
        sla_deadline = discovered_at + sla.resolution_timedelta
        escalation_time = discovered_at + sla.escalation_timedelta
        
        async with self.postgres.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO red_team_findings
                (finding_id, title, severity, attack_type, description, 
                 impact, reproduction_steps, affected_components, bypass_rate,
                 discovered_at, discovered_by, sla_deadline, escalation_time,
                 status, sla_status)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15)
                """,
                finding_id,
                title,
                severity,
                attack_type,
                description,
                impact,
                json.dumps(reproduction_steps),
                json.dumps(affected_components),
                bypass_rate,
                discovered_at,
                discovered_by,
                sla_deadline,
                escalation_time,
                FindingStatus.OPEN.value,
                SLAStatus.ON_TRACK.value
            )
        
        logger.info(f"✅ Finding created: {finding_id} ({severity})")
        logger.info(f"   SLA deadline: {sla_deadline.strftime('%Y-%m-%d %H:%M UTC')}")
        
        return finding_id
    
    async def update_finding_status(
        self,
        finding_id: str,
        new_status: FindingStatus,
        updated_by: str,
        notes: Optional[str] = None
    ) -> bool:
        """
        Update finding status
        
        Args:
            finding_id: Finding identifier
            new_status: New status
            updated_by: Who made the update
            notes: Optional notes
        
        Returns:
            True if successful
        """
        
        async with self.postgres.acquire() as conn:
            # Get current finding
            finding = await conn.fetchrow(
                "SELECT * FROM red_team_findings WHERE finding_id = $1",
                finding_id
            )
            
            if not finding:
                logger.error(f"Finding not found: {finding_id}")
                return False
            
            # Update status
            await conn.execute(
                """
                UPDATE red_team_findings
                SET status = $1, 
                    updated_at = $2,
                    updated_by = $3
                WHERE finding_id = $4
                """,
                new_status.value,
                datetime.utcnow(),
                updated_by,
                finding_id
            )
            
            # Record status change in history
            await conn.execute(
                """
                INSERT INTO finding_status_history
                (finding_id, old_status, new_status, changed_by, notes, changed_at)
                VALUES ($1, $2, $3, $4, $5, $6)
                """,
                finding_id,
                finding["status"],
                new_status.value,
                updated_by,
                notes,
                datetime.utcnow()
            )
            
            # If closed, record resolution time
            if new_status == FindingStatus.CLOSED:
                resolution_time = datetime.utcnow() - finding["discovered_at"]
                
                await conn.execute(
                    """
                    UPDATE red_team_findings
                    SET closed_at = $1,
                        resolution_hours = $2
                    WHERE finding_id = $3
                    """,
                    datetime.utcnow(),
                    resolution_time.total_seconds() / 3600,
                    finding_id
                )
                
                logger.info(
                    f"✅ Finding closed: {finding_id}\n"
                    f"   Resolution time: {resolution_time.total_seconds() / 3600:.1f} hours"
                )
        
        return True
    
    async def assign_finding(
        self,
        finding_id: str,
        assigned_to: str,
        assigned_by: str
    ) -> bool:
        """
        Assign finding to team member
        
        Args:
            finding_id: Finding identifier
            assigned_to: Assignee email/username
            assigned_by: Who made the assignment
        
        Returns:
            True if successful
        """
        
        async with self.postgres.acquire() as conn:
            await conn.execute(
                """
                UPDATE red_team_findings
                SET assigned_to = $1,
                    assigned_at = $2,
                    assigned_by = $3
                WHERE finding_id = $4
                """,
                assigned_to,
                datetime.utcnow(),
                assigned_by,
                finding_id
            )
        
        logger.info(f"✅ Finding assigned: {finding_id} → {assigned_to}")
        
        return True
    
    async def update_sla_status(self):
        """
        Update SLA status for all open findings
        
        Called periodically to check SLA compliance
        """
        
        async with self.postgres.acquire() as conn:
            # Get all open findings
            findings = await conn.fetch(
                """
                SELECT finding_id, severity, discovered_at, sla_deadline, 
                       escalation_time, status
                FROM red_team_findings
                WHERE status NOT IN ('closed', 'wont_fix')
                """
            )
            
            for finding in findings:
                now = datetime.utcnow()
                sla_deadline = finding["sla_deadline"]
                escalation_time = finding["escalation_time"]
                
                # Calculate time remaining
                time_remaining = sla_deadline - now
                total_time = sla_deadline - finding["discovered_at"]
                
                # Determine SLA status
                if now > sla_deadline + timedelta(hours=24):
                    # Breached: > 24h overdue
                    sla_status = SLAStatus.BREACHED
                elif now > sla_deadline:
                    # Overdue
                    sla_status = SLAStatus.OVERDUE
                elif now > escalation_time:
                    # At risk: past escalation time
                    sla_status = SLAStatus.AT_RISK
                elif time_remaining < total_time * 0.25:
                    # At risk: < 25% time remaining
                    sla_status = SLAStatus.AT_RISK
                else:
                    # On track
                    sla_status = SLAStatus.ON_TRACK
                
                # Update SLA status
                await conn.execute(
                    """
                    UPDATE red_team_findings
                    SET sla_status = $1,
                        time_remaining_hours = $2
                    WHERE finding_id = $3
                    """,
                    sla_status.value,
                    max(0, time_remaining.total_seconds() / 3600),
                    finding["finding_id"]
                )
                
                # Log critical SLA issues
                if sla_status == SLAStatus.BREACHED:
                    logger.critical(
                        f"🚨 SLA BREACHED: {finding['finding_id']} "
                        f"({finding['severity']})"
                    )
                elif sla_status == SLAStatus.OVERDUE:
                    logger.error(
                        f"⚠️  SLA OVERDUE: {finding['finding_id']} "
                        f"({finding['severity']})"
                    )
    
    async def get_findings_by_status(
        self,
        status: Optional[FindingStatus] = None,
        severity: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Get findings by status/severity
        
        Args:
            status: Filter by status (optional)
            severity: Filter by severity (optional)
        
        Returns:
            List of findings
        """
        
        where_clauses = []
        params = []
        param_idx = 1
        
        if status:
            where_clauses.append(f"status = ${param_idx}")
            params.append(status.value)
            param_idx += 1
        
        if severity:
            where_clauses.append(f"severity = ${param_idx}")
            params.append(severity)
            param_idx += 1
        
        query = "SELECT * FROM red_team_findings"
        if where_clauses:
            query += " WHERE " + " AND ".join(where_clauses)
        query += " ORDER BY severity, discovered_at DESC"
        
        async with self.postgres.acquire() as conn:
            rows = await conn.fetch(query, *params)
        
        return [dict(row) for row in rows]
    
    async def get_sla_report(self) -> Dict[str, Any]:
        """
        Generate SLA compliance report
        
        Returns:
            SLA statistics and metrics
        """
        
        async with self.postgres.acquire() as conn:
            # Total findings
            total = await conn.fetchval(
                "SELECT COUNT(*) FROM red_team_findings"
            )
            
            # Open findings
            open_findings = await conn.fetchval(
                "SELECT COUNT(*) FROM red_team_findings WHERE status NOT IN ('closed', 'wont_fix')"
            )
            
            # SLA status breakdown
            sla_breakdown = await conn.fetch(
                """
                SELECT sla_status, COUNT(*) as count
                FROM red_team_findings
                WHERE status NOT IN ('closed', 'wont_fix')
                GROUP BY sla_status
                """
            )
            
            # Severity breakdown
            severity_breakdown = await conn.fetch(
                """
                SELECT severity, COUNT(*) as count
                FROM red_team_findings
                WHERE status NOT IN ('closed', 'wont_fix')
                GROUP BY severity
                ORDER BY severity
                """
            )
            
            # Average resolution time by severity
            avg_resolution = await conn.fetch(
                """
                SELECT severity, AVG(resolution_hours) as avg_hours
                FROM red_team_findings
                WHERE status = 'closed' AND resolution_hours IS NOT NULL
                GROUP BY severity
                """
            )
            
            # SLA compliance rate
            total_closed = await conn.fetchval(
                "SELECT COUNT(*) FROM red_team_findings WHERE status = 'closed'"
            )
            
            sla_met = await conn.fetchval(
                """
                SELECT COUNT(*) FROM red_team_findings
                WHERE status = 'closed' 
                AND closed_at <= sla_deadline
                """
            )
            
            compliance_rate = (sla_met / total_closed * 100) if total_closed > 0 else 0
        
        report = {
            "timestamp": datetime.utcnow().isoformat(),
            "total_findings": total,
            "open_findings": open_findings,
            "sla_status": {row["sla_status"]: row["count"] for row in sla_breakdown},
            "severity_breakdown": {row["severity"]: row["count"] for row in severity_breakdown},
            "avg_resolution_hours": {row["severity"]: float(row["avg_hours"]) for row in avg_resolution if row["avg_hours"]},
            "sla_compliance_rate": compliance_rate,
            "sla_met": sla_met,
            "total_closed": total_closed
        }
        
        logger.info("="*60)
        logger.info("SLA COMPLIANCE REPORT")
        logger.info("="*60)
        logger.info(f"Total findings: {total}")
        logger.info(f"Open findings: {open_findings}")
        logger.info(f"SLA compliance rate: {compliance_rate:.1f}%")
        logger.info(f"\nSeverity breakdown:")
        for severity, count in report["severity_breakdown"].items():
            logger.info(f"  {severity}: {count}")
        logger.info("="*60)
        
        return report
    
    async def escalate_overdue_findings(self):
        """
        Escalate overdue findings
        
        Sends notifications for SLA breaches
        """
        
        async with self.postgres.acquire() as conn:
            # Get overdue and breached findings
            overdue = await conn.fetch(
                """
                SELECT finding_id, title, severity, assigned_to, 
                       sla_deadline, time_remaining_hours
                FROM red_team_findings
                WHERE sla_status IN ('overdue', 'breached')
                AND status NOT IN ('closed', 'wont_fix')
                ORDER BY severity, sla_deadline
                """
            )
            
            for finding in overdue:
                logger.critical(
                    f"🚨 ESCALATION REQUIRED\n"
                    f"   Finding: {finding['finding_id']}\n"
                    f"   Title: {finding['title']}\n"
                    f"   Severity: {finding['severity']}\n"
                    f"   Assigned to: {finding['assigned_to'] or 'UNASSIGNED'}\n"
                    f"   SLA deadline: {finding['sla_deadline']}\n"
                    f"   Overdue by: {abs(finding['time_remaining_hours']):.1f} hours"
                )
                
                # In production, would send email/Slack notification
                # await self._send_escalation_notification(finding)