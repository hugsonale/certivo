"""
Explainability System
Detailed audit trail for every risk decision
"""

import asyncpg
from typing import Dict, Any, Optional, List
from datetime import datetime
from dataclasses import dataclass
from enum import Enum
import json
import logging

from risk_scoring import RiskAssessment, RiskFactor

logger = logging.getLogger(__name__)


class ExplainabilityLevel(str, Enum):
    """Detail level for explanations"""
    SUMMARY = "summary"      # High-level decision summary
    DETAILED = "detailed"    # Full factor breakdown
    TECHNICAL = "technical"  # Raw signals and calculations


@dataclass
class ExplainabilityRecord:
    """Complete explainability record for a decision"""
    record_id: str
    session_id: str
    device_id: str
    customer_id: str
    
    # Decision details
    decision: str
    overall_risk_score: float
    threshold_used: float
    passed: bool
    
    # Factor breakdown
    factor_scores: Dict[str, Dict[str, Any]]
    
    # Explanations at different levels
    summary_explanation: str
    detailed_explanation: str
    technical_details: Dict[str, Any]
    
    # Primary concerns
    primary_concerns: List[str]
    
    # Policy context
    policy_id: str
    policy_version: int
    
    # Metadata
    timestamp: datetime
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "record_id": self.record_id,
            "session_id": self.session_id,
            "device_id": self.device_id,
            "customer_id": self.customer_id,
            "decision": self.decision,
            "overall_risk_score": round(self.overall_risk_score, 4),
            "threshold_used": round(self.threshold_used, 4),
            "passed": self.passed,
            "factor_scores": self.factor_scores,
            "summary_explanation": self.summary_explanation,
            "detailed_explanation": self.detailed_explanation,
            "technical_details": self.technical_details,
            "primary_concerns": self.primary_concerns,
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "timestamp": self.timestamp.isoformat()
        }
    
    def get_explanation(self, level: ExplainabilityLevel = ExplainabilityLevel.SUMMARY) -> str:
        """Get explanation at specified detail level"""
        if level == ExplainabilityLevel.SUMMARY:
            return self.summary_explanation
        elif level == ExplainabilityLevel.DETAILED:
            return self.detailed_explanation
        else:
            return json.dumps(self.technical_details, indent=2)


class ExplainabilityEngine:
    """
    Explainability engine for risk decisions
    
    Features:
    - Detailed audit trail for every decision
    - Multi-level explanations (summary, detailed, technical)
    - Primary concern identification
    - Full signal transparency
    - Query by session/device/customer
    """
    
    def __init__(self, postgres_pool: asyncpg.Pool):
        self.postgres = postgres_pool
    
    async def create_explainability_record(
        self,
        assessment: RiskAssessment,
        customer_id: str,
        policy_id: str,
        policy_version: int
    ) -> ExplainabilityRecord:
        """
        Create explainability record from risk assessment
        
        Args:
            assessment: Risk assessment result
            customer_id: Customer identifier
            policy_id: Policy used
            policy_version: Policy version
        
        Returns:
            Explainability record
        """
        
        # Generate record ID
        record_id = f"EXP-{assessment.session_id}-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
        
        # Build factor scores breakdown
        factor_scores = {}
        for factor, score_obj in assessment.factors.items():
            factor_scores[factor.value] = {
                "score": round(score_obj.score, 4),
                "weight": round(score_obj.weight, 4),
                "weighted_contribution": round(score_obj.weighted_score(), 4),
                "confidence": round(score_obj.confidence, 4),
                "explanation": score_obj.explanation,
                "signals": score_obj.signals
            }
        
        # Build summary explanation (user-facing)
        summary_explanation = self._build_summary_explanation(assessment)
        
        # Build detailed explanation (support/review)
        detailed_explanation = self._build_detailed_explanation(assessment)
        
        # Build technical details (engineering/audit)
        technical_details = {
            "assessment": assessment.to_dict(),
            "calculation_method": "weighted_factor_scoring",
            "factor_weights": {
                k.value: v.weight for k, v in assessment.factors.items()
            },
            "raw_signals": {
                k.value: v.signals for k, v in assessment.factors.items()
            }
        }
        
        record = ExplainabilityRecord(
            record_id=record_id,
            session_id=assessment.session_id,
            device_id=assessment.device_id,
            customer_id=customer_id,
            decision=assessment.decision,
            overall_risk_score=assessment.overall_risk_score,
            threshold_used=assessment.threshold_used,
            passed=assessment.passed,
            factor_scores=factor_scores,
            summary_explanation=summary_explanation,
            detailed_explanation=detailed_explanation,
            technical_details=technical_details,
            primary_concerns=assessment.primary_concerns,
            policy_id=policy_id,
            policy_version=policy_version,
            timestamp=assessment.timestamp
        )
        
        # Store in database
        await self._store_record(record)
        
        logger.info(
            f"📝 Explainability record created: {record_id}\n"
            f"   Session: {assessment.session_id}\n"
            f"   Decision: {assessment.decision}\n"
            f"   Risk Score: {assessment.overall_risk_score:.2%}"
        )
        
        return record
    
    def _build_summary_explanation(self, assessment: RiskAssessment) -> str:
        """Build user-facing summary explanation"""
        
        if assessment.decision == "approve":
            return (
                f"Your verification was approved. "
                f"All security checks passed successfully."
            )
        elif assessment.decision == "deny":
            concerns = "; ".join(assessment.primary_concerns[:2])
            return (
                f"Verification denied due to security concerns. "
                f"Issues detected: {concerns}. "
                f"Please contact support if you believe this is an error."
            )
        elif assessment.decision == "review":
            return (
                f"Your verification requires additional review. "
                f"Our security team will review your request shortly. "
                f"You will be notified of the outcome."
            )
        else:  # challenge
            return (
                f"Additional verification required for security. "
                f"Please complete the additional challenge to proceed."
            )
    
    def _build_detailed_explanation(self, assessment: RiskAssessment) -> str:
        """Build detailed explanation for support/review"""
        
        lines = [
            f"Risk Assessment: {assessment.session_id}",
            f"Overall Risk Score: {assessment.overall_risk_score:.2%}",
            f"Threshold: {assessment.threshold_used:.2%}",
            f"Decision: {assessment.decision.upper()}",
            f"Risk Level: {assessment.risk_level.value.upper()}",
            "",
            "Factor Breakdown:"
        ]
        
        # Sort factors by weighted contribution
        sorted_factors = sorted(
            assessment.factors.items(),
            key=lambda x: x[1].weighted_score(),
            reverse=True
        )
        
        for factor, score_obj in sorted_factors:
            lines.append(
                f"  {factor.value.upper()}:"
            )
            lines.append(
                f"    Score: {score_obj.score:.2%} "
                f"(weight: {score_obj.weight:.1%}, "
                f"contribution: {score_obj.weighted_score():.2%})"
            )
            lines.append(
                f"    {score_obj.explanation}"
            )
            lines.append("")
        
        if assessment.primary_concerns:
            lines.append("Primary Concerns:")
            for concern in assessment.primary_concerns:
                lines.append(f"  • {concern}")
            lines.append("")
        
        lines.append(f"Assessment Timestamp: {assessment.timestamp.isoformat()}")
        
        return "\n".join(lines)
    
    async def _store_record(self, record: ExplainabilityRecord):
        """Store explainability record in database"""
        
        async with self.postgres.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO explainability_records
                (record_id, session_id, device_id, customer_id, decision,
                 overall_risk_score, threshold_used, passed, factor_scores,
                 summary_explanation, detailed_explanation, technical_details,
                 primary_concerns, policy_id, policy_version, timestamp)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16)
                """,
                record.record_id,
                record.session_id,
                record.device_id,
                record.customer_id,
                record.decision,
                record.overall_risk_score,
                record.threshold_used,
                record.passed,
                json.dumps(record.factor_scores),
                record.summary_explanation,
                record.detailed_explanation,
                json.dumps(record.technical_details),
                record.primary_concerns,
                record.policy_id,
                record.policy_version,
                record.timestamp
            )
    
    async def get_record(
        self,
        session_id: Optional[str] = None,
        record_id: Optional[str] = None
    ) -> Optional[ExplainabilityRecord]:
        """
        Retrieve explainability record
        
        Args:
            session_id: Session identifier
            record_id: Record identifier
        
        Returns:
            Explainability record or None
        """
        
        if not session_id and not record_id:
            raise ValueError("Must provide session_id or record_id")
        
        query = "SELECT * FROM explainability_records WHERE "
        
        if record_id:
            query += "record_id = $1"
            param = record_id
        else:
            query += "session_id = $1 ORDER BY timestamp DESC LIMIT 1"
            param = session_id
        
        async with self.postgres.acquire() as conn:
            row = await conn.fetchrow(query, param)
        
        if not row:
            return None
        
        return ExplainabilityRecord(
            record_id=row["record_id"],
            session_id=row["session_id"],
            device_id=row["device_id"],
            customer_id=row["customer_id"],
            decision=row["decision"],
            overall_risk_score=float(row["overall_risk_score"]),
            threshold_used=float(row["threshold_used"]),
            passed=row["passed"],
            factor_scores=json.loads(row["factor_scores"]),
            summary_explanation=row["summary_explanation"],
            detailed_explanation=row["detailed_explanation"],
            technical_details=json.loads(row["technical_details"]),
            primary_concerns=row["primary_concerns"],
            policy_id=row["policy_id"],
            policy_version=row["policy_version"],
            timestamp=row["timestamp"]
        )
    
    async def get_records_by_device(
        self,
        device_id: str,
        limit: int = 10
    ) -> List[ExplainabilityRecord]:
        """Get recent records for device"""
        
        async with self.postgres.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM explainability_records
                WHERE device_id = $1
                ORDER BY timestamp DESC
                LIMIT $2
                """,
                device_id,
                limit
            )
        
        return [
            ExplainabilityRecord(
                record_id=row["record_id"],
                session_id=row["session_id"],
                device_id=row["device_id"],
                customer_id=row["customer_id"],
                decision=row["decision"],
                overall_risk_score=float(row["overall_risk_score"]),
                threshold_used=float(row["threshold_used"]),
                passed=row["passed"],
                factor_scores=json.loads(row["factor_scores"]),
                summary_explanation=row["summary_explanation"],
                detailed_explanation=row["detailed_explanation"],
                technical_details=json.loads(row["technical_details"]),
                primary_concerns=row["primary_concerns"],
                policy_id=row["policy_id"],
                policy_version=row["policy_version"],
                timestamp=row["timestamp"]
            )
            for row in rows
        ]
    
    async def get_denied_records(
        self,
        customer_id: Optional[str] = None,
        hours: int = 24,
        limit: int = 100
    ) -> List[ExplainabilityRecord]:
        """Get recent denied/flagged records"""
        
        from datetime import timedelta
        since = datetime.utcnow() - timedelta(hours=hours)
        
        where_clauses = ["decision IN ('deny', 'review')", "timestamp >= $1"]
        params = [since]
        param_idx = 2
        
        if customer_id:
            where_clauses.append(f"customer_id = ${param_idx}")
            params.append(customer_id)
            param_idx += 1
        
        query = f"""
            SELECT * FROM explainability_records
            WHERE {' AND '.join(where_clauses)}
            ORDER BY timestamp DESC
            LIMIT ${param_idx}
        """
        params.append(limit)
        
        async with self.postgres.acquire() as conn:
            rows = await conn.fetch(query, *params)
        
        return [
            ExplainabilityRecord(
                record_id=row["record_id"],
                session_id=row["session_id"],
                device_id=row["device_id"],
                customer_id=row["customer_id"],
                decision=row["decision"],
                overall_risk_score=float(row["overall_risk_score"]),
                threshold_used=float(row["threshold_used"]),
                passed=row["passed"],
                factor_scores=json.loads(row["factor_scores"]),
                summary_explanation=row["summary_explanation"],
                detailed_explanation=row["detailed_explanation"],
                technical_details=json.loads(row["technical_details"]),
                primary_concerns=row["primary_concerns"],
                policy_id=row["policy_id"],
                policy_version=row["policy_version"],
                timestamp=row["timestamp"]
            )
            for row in rows
        ]
    
    async def generate_denial_report(
        self,
        session_id: str
    ) -> Dict[str, Any]:
        """
        Generate comprehensive denial report for customer inquiry
        
        Args:
            session_id: Session identifier
        
        Returns:
            Formatted denial report
        """
        
        record = await self.get_record(session_id=session_id)
        
        if not record:
            raise ValueError(f"No explainability record found for session: {session_id}")
        
        # Build human-readable report
        report = {
            "session_id": session_id,
            "timestamp": record.timestamp.isoformat(),
            "decision": record.decision,
            "reason_summary": record.summary_explanation,
            
            "risk_assessment": {
                "overall_score": f"{record.overall_risk_score:.1%}",
                "threshold": f"{record.threshold_used:.1%}",
                "risk_level": self._score_to_level(record.overall_risk_score)
            },
            
            "factors_analyzed": {},
            
            "primary_concerns": record.primary_concerns,
            
            "next_steps": self._get_next_steps(record),
            
            "support_contact": {
                "email": "support@certivo.com",
                "reference_id": record.record_id
            }
        }
        
        # Add factor details
        for factor_name, factor_data in record.factor_scores.items():
            report["factors_analyzed"][factor_name] = {
                "score": f"{factor_data['score']:.1%}",
                "impact": f"{factor_data['weighted_contribution']:.1%}",
                "assessment": factor_data['explanation']
            }
        
        return report
    
    def _score_to_level(self, score: float) -> str:
        """Convert risk score to level"""
        if score >= 0.75:
            return "Critical Risk"
        elif score >= 0.50:
            return "High Risk"
        elif score >= 0.25:
            return "Moderate Risk"
        else:
            return "Low Risk"
    
    def _get_next_steps(self, record: ExplainabilityRecord) -> List[str]:
        """Get recommended next steps based on decision"""
        
        if record.decision == "deny":
            return [
                "Contact support with reference ID for manual review",
                "Ensure you are using a trusted device and network",
                "Try again from a different location or device",
                "Verify your account information is up to date"
            ]
        elif record.decision == "review":
            return [
                "Your request is under review by our security team",
                "You will receive a notification within 24 hours",
                "No action required at this time",
                "Contact support if urgent"
            ]
        else:
            return [
                "Complete the additional verification challenge",
                "Ensure good lighting and camera position",
                "Follow the on-screen instructions carefully"
            ]