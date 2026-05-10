"""
Comprehensive Red-Team Test Suite

Acceptance Criteria:
1. Weighted bypass score < 0.05 (5%)
2. Findings tracked with SLA: P0 24h, P1 7d
"""

import pytest
import asyncio
import asyncpg
import redis.asyncio as redis
import sys
import os

sys.path.insert(0, 'red_team')

from framework import RedTeamFramework, AttackType
from attacks.replay_attack import ReplayAttackModule
from attacks.video_injection import VideoInjectionModule
from attacks.headless_automation import HeadlessAutomationModule
from attacks.prompt_prediction import PromptPredictionModule
from attacks.device_spoofing import DeviceSpoofingModule
from risk_gate import RiskGate
from finding_tracker import FindingTracker


class TestRedTeamSuite:
    """
    Full red-team test suite
    
    Tests all attack vectors and validates risk gate
    """
    
    @pytest.fixture
    async def framework(self):
        """Setup red-team framework"""
        
        postgres_pool = await asyncpg.create_pool(
            "postgresql://certivo:certivo@localhost:5432/certivo"
        )
        
        redis_client = await redis.from_url("redis://localhost:6379")
        
        framework = RedTeamFramework(
            api_base_url="http://localhost:8000",
            postgres_pool=postgres_pool,
            redis_client=redis_client
        )
        
        # Register attack modules
        framework.register_attack_module(
            AttackType.REPLAY_ATTACK,
            ReplayAttackModule()
        )
        
        framework.register_attack_module(
            AttackType.VIDEO_INJECTION,
            VideoInjectionModule()
        )
        
        framework.register_attack_module(
            AttackType.HEADLESS_AUTOMATION,
            HeadlessAutomationModule()
        )
        
        framework.register_attack_module(
            AttackType.PROMPT_PREDICTION,
            PromptPredictionModule()
        )
        
        framework.register_attack_module(
            AttackType.DEVICE_SPOOFING,
            DeviceSpoofingModule()
        )
        
        yield framework
        
        await postgres_pool.close()
        await redis_client.close()
    
    @pytest.mark.asyncio
    async def test_replay_attack_resistance(self, framework):
        """
        Test resistance to replay attacks
        
        Target: < 5% bypass rate
        """
        
        result = await framework.run_attack(
            AttackType.REPLAY_ATTACK,
            num_attempts=100
        )
        
        assert result.bypass_rate < 0.05, \
            f"Replay attack bypass rate too high: {result.bypass_rate:.2%}"
        
        print(f"✅ Replay attack resistance: {(1-result.bypass_rate)*100:.1f}%")
    
    @pytest.mark.asyncio
    async def test_video_injection_resistance(self, framework):
        """
        Test resistance to video injection attacks
        
        Target: < 5% bypass rate
        """
        
        result = await framework.run_attack(
            AttackType.VIDEO_INJECTION,
            num_attempts=100,
            config={"injection_type": "deepfake"}
        )
        
        assert result.bypass_rate < 0.05, \
            f"Video injection bypass rate too high: {result.bypass_rate:.2%}"
        
        print(f"✅ Video injection resistance: {(1-result.bypass_rate)*100:.1f}%")
    
    @pytest.mark.asyncio
    async def test_headless_automation_detection(self, framework):
        """
        Test detection of headless automation
        
        Target: < 5% bypass rate
        """
        
        result = await framework.run_attack(
            AttackType.HEADLESS_AUTOMATION,
            num_attempts=100,
            config={"tool": "puppeteer"}
        )
        
        assert result.bypass_rate < 0.05, \
            f"Headless automation bypass rate too high: {result.bypass_rate:.2%}"
        
        print(f"✅ Headless detection: {(1-result.bypass_rate)*100:.1f}%")
    
    @pytest.mark.asyncio
    async def test_prompt_prediction_resistance(self, framework):
        """
        Test resistance to challenge prediction
        
        Target: < 5% bypass rate
        """
        
        result = await framework.run_attack(
            AttackType.PROMPT_PREDICTION,
            num_attempts=100,
            config={"type": "entropy_analysis"}
        )
        
        assert result.bypass_rate < 0.05, \
            f"Prompt prediction bypass rate too high: {result.bypass_rate:.2%}"
        
        print(f"✅ Prompt prediction resistance: {(1-result.bypass_rate)*100:.1f}%")
    
    @pytest.mark.asyncio
    async def test_device_spoofing_detection(self, framework):
        """
        Test detection of device spoofing
        
        Target: < 5% bypass rate
        """
        
        result = await framework.run_attack(
            AttackType.DEVICE_SPOOFING,
            num_attempts=100,
            config={"type": "device_id_clone"}
        )
        
        assert result.bypass_rate < 0.05, \
            f"Device spoofing bypass rate too high: {result.bypass_rate:.2%}"
        
        print(f"✅ Device spoofing detection: {(1-result.bypass_rate)*100:.1f}%")
    
    @pytest.mark.asyncio
    async def test_weighted_bypass_score(self, framework):
        """
        ACCEPTANCE CRITERIA 1: Weighted bypass score < 0.05
        
        Run full suite and calculate weighted score
        """
        
        print("\n" + "="*60)
        print("RED-TEAM FULL SUITE - RISK GATE VALIDATION")
        print("="*60)
        
        # Run full suite
        summary = await framework.run_full_suite()
        
        # Extract bypass rates
        attack_results = {
            attack: data["bypass_rate"]
            for attack, data in summary["results"].items()
        }
        
        # Validate risk gate
        validation = RiskGate.validate_launch_readiness(attack_results)
        
        # Store validation
        postgres_pool = framework.postgres
        async with postgres_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO risk_gate_validations
                (test_run_id, weighted_bypass_score, threshold, passed,
                 attack_results, findings_count, p0_count, p1_count, validated_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                """,
                f"test_run_{int(asyncio.get_event_loop().time())}",
                validation["weighted_score"],
                validation["threshold"],
                validation["ready"],
                json.dumps(attack_results),
                len(validation["failing_attacks"]),
                sum(1 for a in validation["failing_attacks"] if a.get("severity") == "P0"),
                sum(1 for a in validation["failing_attacks"] if a.get("severity") == "P1"),
                datetime.utcnow()
            )
        
        print("\n" + "="*60)
        print("RISK GATE RESULT")
        print("="*60)
        print(f"Weighted Bypass Score: {validation['weighted_score']:.4f}")
        print(f"Threshold: {validation['threshold']}")
        print(f"Status: {validation['status']}")
        print("="*60)
        
        # ACCEPTANCE CRITERIA: Must pass risk gate
        assert validation["ready"], \
            f"Risk gate failed: weighted score {validation['weighted_score']:.4f} >= {validation['threshold']}"
        
        print(f"\n✅ ACCEPTANCE CRITERIA MET: Weighted bypass score < 0.05")


class TestFindingTracking:
    """
    Test finding tracking with SLA
    
    Acceptance Criteria: Findings tracked with SLA (P0 24h, P1 7d)
    """
    
    @pytest.fixture
    async def tracker(self):
        """Setup finding tracker"""
        
        postgres_pool = await asyncpg.create_pool(
            "postgresql://certivo:certivo@localhost:5432/certivo"
        )
        
        tracker = FindingTracker(postgres_pool)
        
        yield tracker
        
        await postgres_pool.close()
    
    @pytest.mark.asyncio
    async def test_p0_sla_24_hours(self, tracker):
        """
        ACCEPTANCE CRITERIA 2a: P0 findings have 24h SLA
        """
        
        finding_id = await tracker.create_finding(
            finding_id="RT-TEST-P0-001",
            title="Critical Bypass - Replay Attack",
            severity="P0",
            attack_type="replay_attack",
            description="Complete bypass via replay attack",
            impact="Attackers can bypass verification",
            reproduction_steps=["Step 1", "Step 2"],
            affected_components=["token_validation"],
            bypass_rate=0.75
        )
        
        # Get finding
        findings = await tracker.get_findings_by_status(severity="P0")
        finding = [f for f in findings if f["finding_id"] == finding_id][0]
        
        # Calculate SLA duration
        sla_duration = finding["sla_deadline"] - finding["discovered_at"]
        sla_hours = sla_duration.total_seconds() / 3600
        
        assert sla_hours == 24, f"P0 SLA should be 24 hours, got {sla_hours}"
        
        print(f"✅ P0 SLA validated: {sla_hours} hours")
    
    @pytest.mark.asyncio
    async def test_p1_sla_7_days(self, tracker):
        """
        ACCEPTANCE CRITERIA 2b: P1 findings have 7d SLA
        """
        
        finding_id = await tracker.create_finding(
            finding_id="RT-TEST-P1-001",
            title="High Risk - Video Injection",
            severity="P1",
            attack_type="video_injection",
            description="Partial bypass via video injection",
            impact="Significant security gap",
            reproduction_steps=["Step 1", "Step 2"],
            affected_components=["liveness_detection"],
            bypass_rate=0.25
        )
        
        # Get finding
        findings = await tracker.get_findings_by_status(severity="P1")
        finding = [f for f in findings if f["finding_id"] == finding_id][0]
        
        # Calculate SLA duration
        sla_duration = finding["sla_deadline"] - finding["discovered_at"]
        sla_days = sla_duration.total_seconds() / 86400
        
        assert sla_days == 7, f"P1 SLA should be 7 days, got {sla_days}"
        
        print(f"✅ P1 SLA validated: {sla_days} days")
    
    @pytest.mark.asyncio
    async def test_sla_tracking_lifecycle(self, tracker):
        """
        Test complete SLA tracking lifecycle
        """
        
        # Create finding
        finding_id = await tracker.create_finding(
            finding_id="RT-TEST-LIFECYCLE-001",
            title="Test Finding",
            severity="P1",
            attack_type="replay_attack",
            description="Test",
            impact="Test",
            reproduction_steps=["Step 1"],
            affected_components=["test"],
            bypass_rate=0.20
        )
        
        # Assign finding
        await tracker.assign_finding(
            finding_id=finding_id,
            assigned_to="security_team@certivo.com",
            assigned_by="red_team_lead"
        )
        
        # Update status to investigating
        await tracker.update_finding_status(
            finding_id=finding_id,
            new_status=FindingStatus.INVESTIGATING,
            updated_by="security_engineer",
            notes="Started investigation"
        )
        
        # Update SLA status
        await tracker.update_sla_status()
        
        # Get SLA report
        report = await tracker.get_sla_report()
        
        assert report["total_findings"] > 0
        assert report["open_findings"] > 0
        
        print(f"✅ SLA tracking lifecycle validated")
        print(f"   Total findings: {report['total_findings']}")
        print(f"   Open findings: {report['open_findings']}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])