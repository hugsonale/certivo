"""
Integrated Risk Service
Combines risk scoring, policy engine, and explainability
"""

import asyncpg
from typing import Dict, Any, Optional
from datetime import datetime
import logging

from risk_scoring import RiskScoringEngine, RiskAssessment
from policy_engine import PolicyEngine, RiskPolicy
from explainability import ExplainabilityEngine, ExplainabilityRecord

logger = logging.getLogger(__name__)


class IntegratedRiskService:
    """
    Integrated risk assessment service
    
    Features:
    - Risk scoring with custom policies
    - Policy-based decision making
    - Automatic explainability recording
    - No code changes for policy updates
    """
    
    def __init__(self, postgres_pool: asyncpg.Pool):
        self.postgres = postgres_pool
        self.policy_engine = PolicyEngine(postgres_pool)
        self.explainability_engine = ExplainabilityEngine(postgres_pool)
    
    async def assess_and_decide(
        self,
        session_id: str,
        device_id: str,
        customer_id: str,
        liveness_result: Dict[str, Any],
        behavior_data: Dict[str, Any],
        device_data: Dict[str, Any],
        network_data: Dict[str, Any]
    ) -> tuple[RiskAssessment, ExplainabilityRecord]:
        """
        Perform risk assessment and generate explainability record
        
        Args:
            session_id: Session identifier
            device_id: Device identifier
            customer_id: Customer identifier
            liveness_result: Liveness detection results
            behavior_data: Behavioral metrics
            device_data: Device information
            network_data: Network information
        
        Returns:
            (RiskAssessment, ExplainabilityRecord)
        """
        
        # Get customer policy
        policy = await self.policy_engine.get_policy(customer_id)
        
        if not policy:
            # Use default policy
            policy = await self._get_default_policy(customer_id)
        
        # Create risk scoring engine with policy weights
        scoring_engine = RiskScoringEngine(weights=policy.factor_weights)
        
        # Perform risk assessment
        assessment = scoring_engine.assess_risk(
            session_id=session_id,
            device_id=device_id,
            liveness_result=liveness_result,
            behavior_data=behavior_data,
            device_data=device_data,
            network_data=network_data,
            threshold=policy.approve_threshold
        )
        
        # Apply policy thresholds
        assessment = self._apply_policy_thresholds(assessment, policy)
        
        # Store assessment
        await self._store_assessment(assessment, customer_id, policy)
        
        # Create explainability record
        explainability_record = await self.explainability_engine.create_explainability_record(
            assessment=assessment,
            customer_id=customer_id,
            policy_id=policy.policy_id,
            policy_version=policy.version
        )
        
        logger.info(
            f"✅ Risk assessment complete: {session_id}\n"
            f"   Customer: {customer_id}\n"
            f"   Risk Score: {assessment.overall_risk_score:.2%}\n"
            f"   Decision: {assessment.decision}\n"
            f"   Policy: {policy.policy_id} v{policy.version}\n"
            f"   Explainability: {explainability_record.record_id}"
        )
        
        return assessment, explainability_record
    
    def _apply_policy_thresholds(
        self,
        assessment: RiskAssessment,
        policy: RiskPolicy
    ) -> RiskAssessment:
        """Apply policy-specific thresholds to assessment"""
        
        score = assessment.overall_risk_score
        
        # Determine decision based on policy thresholds
        if score < policy.approve_threshold:
            decision = "approve"
            passed = True
        elif score < policy.review_threshold:
            decision = "challenge"
            passed = False
        elif score < policy.deny_threshold:
            decision = "review"
            passed = False
        else:
            decision = "deny"
            passed = False
        
        # Update assessment
        assessment.decision = decision
        assessment.passed = passed
        assessment.threshold_used = policy.approve_threshold
        
        # Update explanation
        if decision == "approve":
            assessment.explanation = (
                f"Risk score {score:.2%} below approval threshold {policy.approve_threshold:.2%}. "
                f"Verification approved."
            )
        elif decision == "deny":
            assessment.explanation = (
                f"Risk score {score:.2%} above denial threshold {policy.deny_threshold:.2%}. "
                f"Verification denied. Primary concerns: {'; '.join(assessment.primary_concerns)}"
            )
        elif decision == "review":
            assessment.explanation = (
                f"Risk score {score:.2%} requires manual review "
                f"(threshold: {policy.review_threshold:.2%}). "
                f"Primary concerns: {'; '.join(assessment.primary_concerns)}"
            )
        else:
            assessment.explanation = (
                f"Risk score {score:.2%} requires additional verification "
                f"(threshold: {policy.review_threshold:.2%})."
            )
        
        return assessment
    
    async def _get_default_policy(self, customer_id: str) -> RiskPolicy:
        """Create default policy for customer"""
        
        return await self.policy_engine.create_policy(
            customer_id=customer_id,
            policy_name="Default Policy",
            approve_threshold=0.30,
            review_threshold=0.50,
            deny_threshold=0.75,
            created_by="system"
        )
    
    async def _store_assessment(
        self,
        assessment: RiskAssessment,
        customer_id: str,
        policy: RiskPolicy
    ):
        """Store risk assessment in database"""
        
        async with self.postgres.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO risk_assessments
                (session_id, device_id, customer_id, overall_risk_score,
                 risk_level, decision, passed, factor_scores, policy_id,
                 policy_version, threshold_used, assessed_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
                """,
                assessment.session_id,
                assessment.device_id,
                customer_id,
                assessment.overall_risk_score,
                assessment.risk_level.value,
                assessment.decision,
                assessment.passed,
                json.dumps({k.value: v.to_dict() for k, v in assessment.factors.items()}),
                policy.policy_id,
                policy.version,
                assessment.threshold_used,
                assessment.timestamp
            )