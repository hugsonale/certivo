"""
Capacity Target Tests

Acceptance Criteria:
1. Load tests with realistic video payload distributions
2. No single-node bottlenecks (DB, queue, storage validated)
"""

import pytest
import asyncio
import sys
import os

sys.path.insert(0, 'services/shared')
sys.path.insert(0, 'tests/load')

from capacity_planner import CapacityPlanner, ScalingPhase, VideoPayloadDistribution
from load_test_framework import LoadTester, LoadTestConfig
from bottleneck_validator import BottleneckValidator


class TestCapacityPlanning:
    """Test capacity planning calculations"""
    
    def test_phase_1_capacity_plan(self):
        """
        Test Phase 1 capacity plan (10k/day)
        """
        
        planner = CapacityPlanner()
        plan = planner.generate_capacity_plan(ScalingPhase.PHASE_1)
        
        print(f"\n📊 Phase 1 Capacity Plan (10k/day):")
        print(f"   Daily: {plan['target']['daily_verifications']:,}")
        print(f"   Peak RPS: {plan['target']['peak_verifications_per_second']:.2f}")
        print(f"   Total Instances: {plan['totals']['total_instances']}")
        print(f"   Total CPU: {plan['totals']['total_cpu_cores']}")
        print(f"   Total Memory: {plan['totals']['total_memory_gb']} GB")
        print(f"   Storage (90d): {plan['totals']['90_day_storage_gb']:.1f} GB")
        print(f"   Cost: ${plan['costs_estimate']['total_per_month_usd']:,.2f}/month")
        
        # Verify plan meets target
        assert plan['target']['daily_verifications'] == 10_000
        assert plan['totals']['total_instances'] > 0
        assert plan['bottleneck_analysis']['single_node_issues'] == 0
        
        print("\n✅ Phase 1 capacity plan validated")
    
    def test_phase_2_capacity_plan(self):
        """
        Test Phase 2 capacity plan (100k/day)
        """
        
        planner = CapacityPlanner()
        plan = planner.generate_capacity_plan(ScalingPhase.PHASE_2)
        
        print(f"\n📊 Phase 2 Capacity Plan (100k/day):")
        print(f"   Daily: {plan['target']['daily_verifications']:,}")
        print(f"   Peak RPS: {plan['target']['peak_verifications_per_second']:.2f}")
        print(f"   Total Instances: {plan['totals']['total_instances']}")
        print(f"   Total CPU: {plan['totals']['total_cpu_cores']}")
        print(f"   Total Memory: {plan['totals']['total_memory_gb']} GB")
        print(f"   Storage (90d): {plan['totals']['90_day_storage_gb']:.1f} GB")
        print(f"   Cost: ${plan['costs_estimate']['total_per_month_usd']:,.2f}/month")
        
        # Verify plan meets target
        assert plan['target']['daily_verifications'] == 100_000
        assert plan['totals']['total_instances'] > 0
        assert plan['bottleneck_analysis']['single_node_issues'] == 0
        
        print("\n✅ Phase 2 capacity plan validated")
    
    def test_phase_3_capacity_plan(self):
        """
        Test Phase 3 capacity plan (1M/day)
        """
        
        planner = CapacityPlanner()
        plan = planner.generate_capacity_plan(ScalingPhase.PHASE_3)
        
        print(f"\n📊 Phase 3 Capacity Plan (1M/day):")
        print(f"   Daily: {plan['target']['daily_verifications']:,}")
        print(f"   Peak RPS: {plan['target']['peak_verifications_per_second']:.2f}")
        print(f"   Total Instances: {plan['totals']['total_instances']}")
        print(f"   Total CPU: {plan['totals']['total_cpu_cores']}")
        print(f"   Total Memory: {plan['totals']['total_memory_gb']} GB")
        print(f"   Storage (90d): {plan['totals']['90_day_storage_gb']:.1f} GB")
        print(f"   Cost: ${plan['costs_estimate']['total_per_month_usd']:,.2f}/month")
        
        # Verify plan meets target
        assert plan['target']['daily_verifications'] == 1_000_000
        assert plan['totals']['total_instances'] > 0
        assert plan['bottleneck_analysis']['single_node_issues'] == 0
        
        print("\n✅ Phase 3 capacity plan validated")
    
    def test_video_payload_distribution(self):
        """
        ACCEPTANCE CRITERIA 1: Realistic video payload distributions
        
        Verify video size distribution is realistic
        """
        
        print("\n" + "="*60)
        print("ACCEPTANCE TEST: Realistic Video Payload Distribution")
        print("="*60)
        
        distribution = VideoPayloadDistribution()
        
        print(f"\n✓ Video Size Distribution:")
        print(f"  P10: {distribution.p10_mb} MB")
        print(f"  P50: {distribution.p50_mb} MB")
        print(f"  P90: {distribution.p90_mb} MB")
        print(f"  P99: {distribution.p99_mb} MB")
        print(f"  Average: {distribution.get_average_size_mb():.2f} MB")
        
        print(f"\n✓ Video Duration Distribution:")
        print(f"  P10: {distribution.p10_seconds}s")
        print(f"  P50: {distribution.p50_seconds}s")
        print(f"  P90: {distribution.p90_seconds}s")
        print(f"  P99: {distribution.p99_seconds}s")
        print(f"  Average: {distribution.get_average_duration_seconds():.2f}s")
        
        print(f"\n✓ Resolution Distribution:")
        print(f"  480p: {distribution.resolution_480p_pct * 100:.0f}%")
        print(f"  720p: {distribution.resolution_720p_pct * 100:.0f}%")
        print(f"  1080p: {distribution.resolution_1080p_pct * 100:.0f}%")
        print(f"  4K: {distribution.resolution_4k_pct * 100:.0f}%")
        
        # Verify distribution is realistic
        assert 2.0 <= distribution.p10_mb <= 3.0
        assert 4.0 <= distribution.p50_mb <= 6.0
        assert 7.0 <= distribution.p90_mb <= 9.0
        assert 10.0 <= distribution.p99_mb <= 15.0
        
        print("\n" + "="*60)
        print("✅ ACCEPTANCE CRITERIA MET: Realistic Video Distribution")
        print("="*60)


class TestLoadTesting:
    """Test load testing framework"""
    
    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_phase_1_load_test(self):
        """
        Test Phase 1 load (10k/day = ~0.12 RPS avg, ~0.35 RPS peak)
        """
        
        print("\n" + "="*60)
        print("LOAD TEST: Phase 1 (10k/day)")
        print("="*60)
        
        config = LoadTestConfig(
            target_rps=0.35,  # Peak load
            duration_seconds=60,  # 1 minute test
            ramp_up_seconds=10
        )
        
        tester = LoadTester(
            api_base_url="http://localhost:8000",
            config=config
        )
        
        result = await tester.run_load_test()
        
        print(f"\n✓ Load Test Results:")
        print(f"  Total Requests: {result.total_requests}")
        print(f"  Success Rate: {result.success_rate:.2f}%")
        print(f"  P50 Latency: {result.p50_latency:.1f}ms")
        print(f"  P95 Latency: {result.p95_latency:.1f}ms")
        
        # Verify success rate
        assert result.success_rate >= 95.0, "Success rate below 95%"
        
        print("\n✅ Phase 1 load test passed")


class TestBottleneckValidation:
    """
    Test bottleneck validation
    
    ACCEPTANCE CRITERIA 2: No single-node bottlenecks
    """
    
    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_no_single_node_bottlenecks(self):
        """
        ACCEPTANCE CRITERIA 2: Validate no single-node bottlenecks
        
        Test all infrastructure components for horizontal scalability
        """
        
        print("\n" + "="*60)
        print("ACCEPTANCE TEST: No Single-Node Bottlenecks")
        print("="*60)
        
        validator = BottleneckValidator(
            postgres_dsn="postgresql://certivo:certivo@localhost:5432/certivo",
            redis_url="redis://localhost:6379",
            s3_endpoint="http://localhost:9000",  # MinIO for testing
            queue_endpoint="http://localhost:15672"  # RabbitMQ
        )
        
        # Run full validation
        report = await validator.run_full_bottleneck_validation()
        
        print(f"\n✓ Bottleneck Validation Report:")
        print(f"  Components Tested: {report['components_tested']}")
        print(f"  Bottlenecks Found: {report['bottlenecks_found']}")
        print(f"  Single-Node Bottlenecks: {report['single_node_bottlenecks']}")
        print(f"  Overall Status: {report['overall_status']}")
        
        print(f"\n✓ Component Details:")
        for result in report['results']:
            status_emoji = "✅" if not result['is_bottleneck'] else "⚠️"
            scale_emoji = "✅" if result['can_scale_horizontally'] else "❌"
            
            print(f"\n  {status_emoji} {result['component']}:")
            print(f"     Target: {result['target_throughput']:.1f} {result['test_type']}")
            print(f"     Actual: {result['actual_throughput']:.1f}")
            print(f"     Utilization: {result['utilization_percentage']:.1f}%")
            print(f"     Can Scale Horizontally: {scale_emoji}")
            
            if result['is_bottleneck']:
                print(f"     ⚠️  Recommendation: {result['recommendation']}")
        
        print("\n" + "="*60)
        
        # ACCEPTANCE CRITERIA: No single-node bottlenecks
        assert report['single_node_bottlenecks'] == 0, \
            f"Found {report['single_node_bottlenecks']} single-node bottlenecks"
        
        print(f"✅ ACCEPTANCE CRITERIA MET: No Single-Node Bottlenecks")
        print("="*60)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s", "--tb=short"])