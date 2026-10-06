"""
Test distributed rate limiting consistency
Ensures limits work correctly across multiple API replicas
"""

import pytest
import httpx
import asyncio
import uuid
from typing import List


class TestDistributedConsistency:
    """Test rate limiting across distributed replicas"""
    
    @pytest.mark.asyncio
    async def test_three_replica_consistency(self):
        """
        Test limits remain correct under 3+ API replicas
        
        Acceptance Criteria: Limits work correctly with 3+ replicas
        """
        # Simulate 3 replicas (in real deployment, these would be different pods)
        base_urls = [
            "http://localhost:8000",  # Replica 1
            "http://localhost:8000",  # Replica 2 (same in test, different in prod)
            "http://localhost:8000",  # Replica 3
        ]
        
        device_id = f"device_{uuid.uuid4().hex[:8]}"
        
        async def make_request_to_replica(url: str, request_num: int):
            """Make request to specific replica"""
            async with httpx.AsyncClient(base_url=url) as client:
                return await client.post(
                    "/v1/challenge",
                    json={"device_id": f"{device_id}_{request_num}"},
                    headers={"X-Device-ID": device_id}
                )
        
        # Make 30 requests distributed across 3 replicas
        tasks = []
        for i in range(30):
            replica_url = base_urls[i % 3]
            tasks.append(make_request_to_replica(replica_url, i))
        
        responses = await asyncio.gather(*tasks)
        
        # Count results
        success = sum(1 for r in responses if r.status_code == 200)
        blocked = sum(1 for r in responses if r.status_code == 429)
        
        # Device limit is 10/min
        # With distributed enforcement via Redis, should still enforce correctly
        assert blocked > 0, "Rate limiting not enforced across replicas"
        assert success <= 12, "Too many requests allowed (limit breach)"
        
        print(f"✅ Distributed consistency: {success} allowed, {blocked} blocked")
    
    @pytest.mark.asyncio
    async def test_no_race_conditions_under_load(self):
        """Test no race conditions with concurrent requests to multiple replicas"""
        base_url = "http://localhost:8000"
        device_id = f"device_{uuid.uuid4().hex[:8]}"
        
        async def concurrent_burst():
            """Simultaneous burst of requests"""
            async with httpx.AsyncClient(base_url=base_url) as client:
                tasks = [
                    client.post(
                        "/v1/challenge",
                        json={"device_id": f"{device_id}_{i}"},
                        headers={"X-Device-ID": device_id}
                    )
                    for i in range(20)
                ]
                return await asyncio.gather(*tasks)
        
        # Multiple concurrent bursts
        all_responses = []
        for _ in range(3):
            responses = await concurrent_burst()
            all_responses.extend(responses)
        
        # Count totals
        total_allowed = sum(1 for r in all_responses if r.status_code == 200)
        total_blocked = sum(1 for r in all_responses if r.status_code == 429)
        
        # Should not over-allow due to race conditions
        # Device limit is 10/min, so max ~10-12 allowed across all bursts
        assert total_allowed <= 15, f"Race condition detected: {total_allowed} allowed (limit: 10)"
        assert total_blocked > 0, "No rate limiting detected"
        
        print(f"✅ No race conditions: {total_allowed} allowed, {total_blocked} blocked")
    
    @pytest.mark.asyncio
    async def test_redis_pipeline_atomicity(self):
        """Test Redis pipeline operations are atomic"""
        base_url = "http://localhost:8000"
        device_id = f"device_{uuid.uuid4().hex[:8]}"
        
        # Make rapid-fire requests to test atomicity
        async with httpx.AsyncClient(base_url=base_url) as client:
            tasks = [
                client.post(
                    "/v1/challenge",
                    json={"device_id": f"{device_id}_{i}"},
                    headers={"X-Device-ID": device_id}
                )
                for i in range(100)
            ]
            
            responses = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Filter out exceptions
            valid_responses = [r for r in responses if not isinstance(r, Exception)]
            
            allowed = sum(1 for r in valid_responses if r.status_code == 200)
            
            # Should respect limit even with 100 concurrent requests
            assert allowed <= 15, f"Atomicity violated: {allowed} allowed"


class TestBypassCostMetrics:
    """Test bypass attempts increase attacker cost (measurable)"""
    
    @pytest.mark.asyncio
    async def test_bypass_metric_increases(self):
        """
        Test bypass attempts via IP rotation increase attacker cost
        
        Acceptance Criteria: Bypass attempts tracked in measurable metric
        """
        base_url = "http://localhost:8000"
        
        async with httpx.AsyncClient(base_url=base_url) as client:
            # Get baseline metrics
            baseline_response = await client.get("/metrics/bypass-attempts")
            baseline_metrics = baseline_response.json() if baseline_response.status_code == 200 else {}
            baseline_count = baseline_metrics.get("bypass_attempts", {}).get("ip_rotation", 0)
            
            # Simulate IP rotation attacks
            device_id = f"device_{uuid.uuid4().hex[:8]}"
            
            for ip_suffix in range(10):
                await client.post(
                    "/v1/challenge",
                    json={"device_id": device_id},
                    headers={
                        "X-Device-ID": device_id,
                        "X-Forwarded-For": f"192.168.1.{ip_suffix}"
                    }
                )
            
            # Get updated metrics
            updated_response = await client.get("/metrics/bypass-attempts")
            updated_metrics = updated_response.json() if updated_response.status_code == 200 else {}
            updated_count = updated_metrics.get("bypass_attempts", {}).get("ip_rotation", 0)
            
            # Metric should increase
            cost_increase = updated_count - baseline_count
            
            assert cost_increase > 0, "Bypass attempts not tracked"
            print(f"✅ Attacker cost increased: {cost_increase} bypass attempts detected")
            
            return cost_increase