"""
Risk Scoring Tests

Acceptance Criteria:
1. Policy changes deploy without code changes
2. Explainability record available for every denial/flag
"""

import pytest
import asyncio
import asyncpg
from datetime import datetime
import sys
import os

sys.path.insert(0, 'services/shared')

from risk_scoring import RiskScoringEngine, RiskFactor, RiskLevel
from policy_engine import PolicyEngine, RiskPolicy
from explainability import ExplainabilityEngine, ExplainabilityLevel
from integrated_risk_service import IntegratedRiskService


class TestRiskScoringEngine:
    """Test risk scoring calculations"""
    
    def test_default_weights(self):
        """Test default weight configuration"""
        
        engine = RiskScoringEngine()
        
        # Verify weights sum to 1.0
        total = sum(engine.weights.values())
        assert abs(total - 1.0) < 0.001, f"Weights must sum to 1.0, got {total}"
        
        # Verify default distribution
        assert engine.weights[RiskFactor.LIVENESS] == 0.40
        assert engine.weights[RiskFactor.BEHAVIOR] == 0.25
        assert engine.weights[RiskFactor.DEVICE] == 0.20
        assert engine.weights[RiskFactor.NETWORK] == 0.15
        
        print("✅ Default weights validated")
    
    def test_custom_weights(self):
        """Test custom weight configuration"""
        
        custom_weights = {
            RiskFactor.LIVENESS: 0.50,
            RiskFactor.BEHAVIOR: 0.30,
            RiskFactor.DEVICE: 0.15,
            RiskFactor.NETWORK: 0.05
        }
        
        engine = RiskScoringEngine(weights=custom_weights)
        
        assert engine.weights[RiskFactor.LIVENESS] == 0.50
        assert engine.weights[RiskFactor.BEHAVIOR] == 0.30
        
        print("✅ Custom weights validated")
    
    def test_liveness_score_calculation(self):
        """Test liveness factor scoring"""
        
        engine = RiskScoringEngine()
        
        # High liveness = low risk
        liveness_result = {
            "overall_liveness_score": 0.95,
            "motion_score": 0.92,
            "temporal_score": 0.94,
            "anti_spoof_score": 0.96,
            "action_score": 0.98,
            "confidence": 0.90
        }
        
        score = engine.calculate_liveness_score(liveness_result)
        
        # Risk score should be inverse (1.0 - 0.95 = 0.05)
        assert score.score < 0.10, "High liveness should result in low risk"
        assert score.factor == RiskFactor.LIVENESS
        assert score.weight == 0.40
        
        print(f"✅ Liveness scoring: {score.score:.2%} risk from 0.95 liveness")
    
    def test_behavior_score_calculation(self):
        """Test behavioral factor scoring"""
        
        engine = RiskScoringEngine()
        
        # Normal behavior
        behavior_data = {
            "recent_failed_attempts": 1,
            "attempts_per_hour": 2,
            "session_exhaustion_rate": 0.1,
            "time_pattern_score": 0.8,
            "automation_detected": False
        }
        
        score = engine.calculate_behavior_score(behavior_data)
        
        assert score.score < 0.30, "Normal behavior should have low risk"
        
        # Suspicious behavior
        suspicious_data = {
            "recent_failed_attempts": 10,
            "attempts_per_hour": 15,
            "session_exhaustion_rate": 0.9,
            "time_pattern_score": 0.2,
            "automation_detected": True
        }
        
        suspicious_score = engine.calculate_behavior_score(suspicious_data)
        
        assert suspicious_score.score > 0.70, "Suspicious behavior should have high risk"
        
        print(f"✅ Behavior scoring: normal={score.score:.2%}, suspicious={suspicious_score.score:.2%}")
    
    def test_device_score_calculation(self):
        """Test device factor scoring"""
        
        engine = RiskScoringEngine()
        
        # Trusted device
        device_data = {
            "is_new_device": False,
            "days_since_first_seen": 90,
            "reputation_score": 0.85,
            "fingerprint_changes": 0,
            "is_compromised": False,
            "is_emulator": False
        }
        
        score = engine.calculate_device_score(device_data)
        
        assert score.score < 0.20, "Trusted device should have low risk"
        
        # Suspicious device
        suspicious_device = {
            "is_new_device": True,
            "days_since_first_seen": 0,
            "reputation_score": 0.15,
            "fingerprint_changes": 8,
            "is_compromised": True,
            "is_emulator": True
        }
        
        suspicious_score = engine.calculate_device_score(suspicious_device)
        
        assert suspicious_score.score > 0.70, "Suspicious device should have high risk"
        
        print(f"✅ Device scoring: trusted={score.score:.2%}, suspicious={suspicious_score.score:.2%}")
    
    def test_network_score_calculation(self):
        """Test network factor scoring"""
        
        engine = RiskScoringEngine()
        
        # Clean network
        network_data = {
            "is_vpn": False,
            "is_proxy": False,
            "is_tor": False,
            "ip_reputation_score": 0.80,
            "is_datacenter": False,
            "asn_risk_score": 0.10,
            "location_mismatch": False
        }
        
        score = engine.calculate_network_score(network_data)
        
        assert score.score < 0.20, "Clean network should have low risk"
        
        # Risky network
        risky_network = {
            "is_vpn": False,
            "is_proxy": False,
            "is_tor": True,
            "ip_reputation_score": 0.10,
            "is_datacenter": True,
            "asn_risk_score": 0.85,
            "location_mismatch": True
        }
        
        risky_score = engine.calculate_network_score(risky_network)
        
        assert risky_score.score > 0.70, "Risky network should have high risk"
        
        print(f"✅ Network scoring: clean={score.score:.2%}, risky={risky_score.score:.2%}")
    
    def test_full_risk_assessment(self):
        """Test complete risk assessment"""
        
        engine = RiskScoringEngine()
        
        # Low risk scenario
        assessment = engine.assess_risk(
            session_id="SES-TEST-001",
            device_id="DEV-TEST-001",
            liveness_result={
                "overall_liveness_score": 0.95,
                "motion_score": 0.92,
                "temporal_score": 0.94,
                "anti_spoof_score": 0.96,
                "action_score": 0.98,
                "confidence": 0.90
            },
            behavior_data={
                "recent_failed_attempts": 0,
                "attempts_per_hour": 1,
                "session_exhaustion_rate": 0.0,
                "time_pattern_score": 0.9,
                "automation_detected": False
            },
            device_data={
                "is_new_device": False,
                "days_since_first_seen": 90,
                "reputation_score": 0.85,
                "fingerprint_changes": 0,
                "is_compromised": False,
                "is_emulator": False
            },
            network_data={
                "is_vpn": False,
                "is_proxy": False,
                "is_tor": False,
                "ip_reputation_score": 0.80,
                "is_datacenter": False,
                "asn_risk_score": 0.10,
                "location_mismatch": False
            },
            threshold=0.50
        )
        
        print(f"\n📊 Low Risk Assessment:")
        print(f"   Overall Score: {assessment.overall_risk_score:.2%}")
        print(f"   Risk Level: {assessment.risk_level.value}")
        print(f"   Decision: {assessment.decision}")
        print(f"   Passed: {assessment.passed}")
        
        assert assessment.overall_risk_score < 0.30, "Low risk scenario should have low score"
        assert assessment.passed, "Low risk should pass"
        assert assessment.decision == "approve"
        
        print("✅ Full risk assessment validated")


class TestPolicyEngine:
    """
    Test policy engine
    
    Acceptance Criteria 1: Policy changes deploy without code changes
    """
    
    @pytest.fixture
    async def engine(self):
        """Setup policy engine"""
        
        postgres_pool = await asyncpg.create_pool(
            "postgresql://certivo:certivo@localhost:5432/certivo"
        )
        
        engine = PolicyEngine(postgres_pool)
        
        yield engine
        
        await postgres_pool.close()
    
    @pytest.mark.asyncio
    async def test_create_policy(self, engine):
        """Test policy creation"""
        
        policy = await engine.create_policy(
            customer_id="CUST-TEST-001",
            policy_name="Test Policy",
            approve_threshold=0.30,
            review_threshold=0.50,
            deny_threshold=0.75,
            created_by="test_user"
        )
        
        assert policy.customer_id == "CUST-TEST-001"
        assert policy.approve_threshold == 0.30
        assert policy.review_threshold == 0.50
        assert policy.deny_threshold == 0.75
        assert policy.version == 1
        
        print("✅ Policy creation validated")
    
    @pytest.mark.asyncio
    async def test_update_policy_without_code_changes(self, engine):
        """
        ACCEPTANCE CRITERIA 1: Policy changes deploy without code changes
        
        Verify policies can be updated via database only
        """
        
        print("\n" + "="*60)
        print("ACCEPTANCE TEST: Policy Updates Without Code Changes")
        print("="*60)
        
        # Create initial policy
        customer_id = "CUST-POLICY-UPDATE-TEST"
        
        initial_policy = await engine.create_policy(
            customer_id=customer_id,
            policy_name="Initial Policy",
            approve_threshold=0.30,
            review_threshold=0.50,
            deny_threshold=0.75,
            created_by="test_admin"
        )
        
        print(f"\n✓ Initial Policy Created:")
        print(f"  Thresholds: {initial_policy.approve_threshold}, {initial_policy.review_threshold}, {initial_policy.deny_threshold}")
        print(f"  Version: {initial_policy.version}")
        
        # Update policy (NO CODE CHANGES)
        updated_policy = await engine.update_policy(
            customer_id=customer_id,
            approve_threshold=0.25,  # More lenient
            review_threshold=0.45,
            deny_threshold=0.70,
            updated_by="security_team"
        )
        
        print(f"\n✓ Policy Updated (No Code Changes):")
        print(f"  New Thresholds: {updated_policy.approve_threshold}, {updated_policy.review_threshold}, {updated_policy.deny_threshold}")
        print(f"  Version: {updated_policy.version}")
        
        # Verify update
        assert updated_policy.approve_threshold == 0.25
        assert updated_policy.review_threshold == 0.45
        assert updated_policy.deny_threshold == 0.70
        assert updated_policy.version == 2
        
        # Retrieve policy (simulate new request)
        retrieved_policy = await engine.get_policy(customer_id, use_cache=False)
        
        assert retrieved_policy.version == 2
        assert retrieved_policy.approve_threshold == 0.25
        
        print(f"\n✓ Policy Retrieved Successfully:")
        print(f"  Version: {retrieved_policy.version}")
        print(f"  Thresholds: {retrieved_policy.approve_threshold}, {retrieved_policy.review_threshold}, {retrieved_policy.deny_threshold}")
        
        print("\n" + "="*60)
        print("✅ ACCEPTANCE CRITERIA MET: Policy Changes Without Code Deploy")
        print("="*60)
    
    @pytest.mark.asyncio
    async def test_custom_factor_weights(self, engine):
        """Test custom factor weight configuration"""
        
        custom_weights = {
            RiskFactor.LIVENESS: 0.50,
            RiskFactor.BEHAVIOR: 0.30,
            RiskFactor.DEVICE: 0.15,
            RiskFactor.NETWORK: 0.05
        }
        
        policy = await engine.create_policy(
            customer_id="CUST-CUSTOM-WEIGHTS",
            policy_name="Custom Weights Policy",
            approve_threshold=0.40,
            review_threshold=0.60,
            deny_threshold=0.80,
            factor_weights=custom_weights,
            created_by="test_user"
        )
        
        assert policy.factor_weights[RiskFactor.LIVENESS] == 0.50
        assert policy.factor_weights[RiskFactor.BEHAVIOR] == 0.30
        
        print("✅ Custom factor weights validated")
    
    @pytest.mark.asyncio
    async def test_policy_versioning(self, engine):
        """Test policy version tracking"""
        
        customer_id = "CUST-VERSION-TEST"
        
        # Create initial
        v1 = await engine.create_policy(
            customer_id=customer_id,
            policy_name="Versioned Policy",
            approve_threshold=0.30,
            review_threshold=0.50,
            deny_threshold=0.75
        )
        
        # Update 1
        v2 = await engine.update_policy(
            customer_id=customer_id,
            approve_threshold=0.35
        )
        
        # Update 2
        v3 = await engine.update_policy(
            customer_id=customer_id,
            review_threshold=0.55
        )
        
        assert v1.version == 1
        assert v2.version == 2
        assert v3.version == 3
        
        print(f"✅ Policy versioning validated: v1 → v2 → v3")


class TestExplainabilityEngine:
    """
    Test explainability system
    
    Acceptance Criteria 2: Explainability record available for every denial/flag
    """
    
    @pytest.fixture
    async def engine(self):
        """Setup explainability engine"""
        
        postgres_pool = await asyncpg.create_pool(
            "postgresql://certivo:certivo@localhost:5432/certivo"
        )
        
        engine = ExplainabilityEngine(postgres_pool)
        
        yield engine
        
        await postgres_pool.close()
    
    @pytest.mark.asyncio
    async def test_create_explainability_record(self, engine):
        """Test explainability record creation"""
        
        # Create mock assessment
        from risk_scoring import RiskAssessment, RiskFactorScore
        
        assessment = RiskAssessment(
            session_id="SES-TEST-EXP-001",
            device_id="DEV-TEST-001",
            overall_risk_score=0.65,
            risk_level=RiskLevel.HIGH,
            factors={
                RiskFactor.LIVENESS: RiskFactorScore(
                    factor=RiskFactor.LIVENESS,
                    score=0.15,
                    weight=0.40,
                    confidence=0.90,
                    signals={"overall_liveness": 0.85},
                    explanation="Strong liveness signals"
                ),
                RiskFactor.BEHAVIOR: RiskFactorScore(
                    factor=RiskFactor.BEHAVIOR,
                    score=0.75,
                    weight=0.25,
                    confidence=0.85,
                    signals={"failed_attempts": 8},
                    explanation="High failure rate detected"
                ),
                RiskFactor.DEVICE: RiskFactorScore(
                    factor=RiskFactor.DEVICE,
                    score=0.30,
                    weight=0.20,
                    confidence=0.90,
                    signals={"is_new_device": True},
                    explanation="New device"
                ),
                RiskFactor.NETWORK: RiskFactorScore(
                    factor=RiskFactor.NETWORK,
                    score=0.20,
                    weight=0.15,
                    confidence=0.80,
                    signals={"is_vpn": True},
                    explanation="VPN detected"
                )
            },
            timestamp=datetime.utcnow(),
            threshold_used=0.50,
            passed=False,
            decision="review",
            primary_concerns=[
                "behavior: High failure rate detected",
                "device: New device"
            ],
            explanation="Risk score 0.65 requires manual review"
        )
        
        # Create explainability record
        record = await engine.create_explainability_record(
            assessment=assessment,
            customer_id="CUST-TEST-001",
            policy_id="POL-TEST-001",
            policy_version=1
        )
        
        assert record.session_id == "SES-TEST-EXP-001"
        assert record.decision == "review"
        assert record.overall_risk_score == 0.65
        assert len(record.primary_concerns) == 2
        
        print(f"✅ Explainability record created: {record.record_id}")
    
    @pytest.mark.asyncio
    async def test_explainability_for_denial(self, engine):
        """
        ACCEPTANCE CRITERIA 2: Explainability available for denials
        """
        
        print("\n" + "="*60)
        print("ACCEPTANCE TEST: Explainability For Every Denial")
        print("="*60)
        
        # Create denied assessment
        from risk_scoring import RiskAssessment, RiskFactorScore
        
        denied_assessment = RiskAssessment(
            session_id="SES-DENIED-001",
            device_id="DEV-DENIED-001",
            overall_risk_score=0.85,
            risk_level=RiskLevel.CRITICAL,
            factors={
                RiskFactor.LIVENESS: RiskFactorScore(
                    factor=RiskFactor.LIVENESS,
                    score=0.70,
                    weight=0.40,
                    confidence=0.75,
                    signals={"overall_liveness": 0.30},
                    explanation="Weak liveness signals, potential spoofing"
                ),
                RiskFactor.BEHAVIOR: RiskFactorScore(
                    factor=RiskFactor.BEHAVIOR,
                    score=0.90,
                    weight=0.25,
                    confidence=0.90,
                    signals={"automation_detected": True, "failed_attempts": 15},
                    explanation="Automation detected, high failure rate"
                ),
                RiskFactor.DEVICE: RiskFactorScore(
                    factor=RiskFactor.DEVICE,
                    score=0.80,
                    weight=0.20,
                    confidence=0.95,
                    signals={"is_emulator": True, "is_compromised": True},
                    explanation="Emulator and compromised device detected"
                ),
                RiskFactor.NETWORK: RiskFactorScore(
                    factor=RiskFactor.NETWORK,
                    score=0.75,
                    weight=0.15,
                    confidence=0.85,
                    signals={"is_tor": True},
                    explanation="Tor exit node detected"
                )
            },
            timestamp=datetime.utcnow(),
            threshold_used=0.50,
            passed=False,
            decision="deny",
            primary_concerns=[
                "behavior: Automation detected, high failure rate",
                "device: Emulator and compromised device detected"
            ],
            explanation="Critical risk score 0.85. Verification denied."
        )
        
        # Create explainability record
        record = await engine.create_explainability_record(
            assessment=denied_assessment,
            customer_id="CUST-DENIED-TEST",
            policy_id="POL-DENIED-TEST",
            policy_version=1
        )
        
        print(f"\n✓ Denial Decision Made:")
        print(f"  Session: {denied_assessment.session_id}")
        print(f"  Risk Score: {denied_assessment.overall_risk_score:.2%}")
        print(f"  Decision: {denied_assessment.decision}")
        
        print(f"\n✓ Explainability Record Created:")
        print(f"  Record ID: {record.record_id}")
        print(f"  Summary: {record.summary_explanation}")
        
        print(f"\n✓ Detailed Explanation:")
        print(record.detailed_explanation)
        
        # Verify record can be retrieved
        retrieved = await engine.get_record(session_id=denied_assessment.session_id)
        
        assert retrieved is not None
        assert retrieved.record_id == record.record_id
        assert retrieved.decision == "deny"
        
        print(f"\n✓ Record Retrieved Successfully:")
        print(f"  Record ID: {retrieved.record_id}")
        print(f"  Can be accessed for audit/appeal")
        
        # Generate denial report
        report = await engine.generate_denial_report(denied_assessment.session_id)
        
        print(f"\n✓ Denial Report Generated:")
        print(f"  Session: {report['session_id']}")
        print(f"  Decision: {report['decision']}")
        print(f"  Primary Concerns: {report['primary_concerns']}")
        print(f"  Support Reference: {report['support_contact']['reference_id']}")
        
        print("\n" + "="*60)
        print("✅ ACCEPTANCE CRITERIA MET: Explainability For Every Denial")
        print("="*60)
    
    @pytest.mark.asyncio
    async def test_multi_level_explanations(self, engine):
        """Test different explanation detail levels"""
        
        # Create mock assessment
        from risk_scoring import RiskAssessment, RiskFactorScore
        
        assessment = RiskAssessment(
            session_id="SES-MULTI-LEVEL",
            device_id="DEV-MULTI",
            overall_risk_score=0.55,
            risk_level=RiskLevel.HIGH,
            factors={
                RiskFactor.LIVENESS: RiskFactorScore(
                    factor=RiskFactor.LIVENESS,
                    score=0.20,
                    weight=0.40,
                    confidence=0.90,
                    signals={},
                    explanation="Good liveness"
                ),
                RiskFactor.BEHAVIOR: RiskFactorScore(
                    factor=RiskFactor.BEHAVIOR,
                    score=0.60,
                    weight=0.25,
                    confidence=0.85,
                    signals={},
                    explanation="Some anomalies"
                ),
                RiskFactor.DEVICE: RiskFactorScore(
                    factor=RiskFactor.DEVICE,
                    score=0.40,
                    weight=0.20,
                    confidence=0.90,
                    signals={},
                    explanation="Moderate risk"
                ),
                RiskFactor.NETWORK: RiskFactorScore(
                    factor=RiskFactor.NETWORK,
                    score=0.30,
                    weight=0.15,
                    confidence=0.80,
                    signals={},
                    explanation="Acceptable"
                )
            },
            timestamp=datetime.utcnow(),
            threshold_used=0.50,
            passed=False,
            decision="review",
            primary_concerns=["behavior: Some anomalies"],
            explanation="Requires review"
        )
        
        record = await engine.create_explainability_record(
            assessment=assessment,
            customer_id="CUST-MULTI",
            policy_id="POL-MULTI",
            policy_version=1
        )
        
        # Get different levels
        summary = record.get_explanation(ExplainabilityLevel.SUMMARY)
        detailed = record.get_explanation(ExplainabilityLevel.DETAILED)
        technical = record.get_explanation(ExplainabilityLevel.TECHNICAL)
        
        assert len(summary) < len(detailed)
        assert "Risk Assessment" in detailed
        assert "assessment" in technical
        
        print("✅ Multi-level explanations validated")


class TestIntegratedRiskService:
    """Test integrated risk service"""
    
    @pytest.fixture
    async def service(self):
        """Setup integrated service"""
        
        postgres_pool = await asyncpg.create_pool(
            "postgresql://certivo:certivo@localhost:5432/certivo"
        )
        
        service = IntegratedRiskService(postgres_pool)
        
        yield service
        
        await postgres_pool.close()
    
    @pytest.mark.asyncio
    async def test_full_integration(self, service):
        """Test complete integrated flow"""
        
        # Perform assessment
        assessment, explainability = await service.assess_and_decide(
            session_id="SES-INTEGRATED-001",
            device_id="DEV-INTEGRATED-001",
            customer_id="CUST-INTEGRATED-001",
            liveness_result={
                "overall_liveness_score": 0.90,
                "motion_score": 0.88,
                "temporal_score": 0.92,
                "anti_spoof_score": 0.91,
                "action_score": 0.89,
                "confidence": 0.90
            },
            behavior_data={
                "recent_failed_attempts": 1,
                "attempts_per_hour": 2,
                "session_exhaustion_rate": 0.1,
                "time_pattern_score": 0.8,
                "automation_detected": False
            },
            device_data={
                "is_new_device": False,
                "days_since_first_seen": 60,
                "reputation_score": 0.75,
                "fingerprint_changes": 1,
                "is_compromised": False,
                "is_emulator": False
            },
            network_data={
                "is_vpn": False,
                "is_proxy": False,
                "is_tor": False,
                "ip_reputation_score": 0.70,
                "is_datacenter": False,
                "asn_risk_score": 0.20,
                "location_mismatch": False
            }
        )
        
        assert assessment is not None
        assert explainability is not None
        assert explainability.session_id == "SES-INTEGRATED-001"
        
        print("✅ Full integration validated")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])