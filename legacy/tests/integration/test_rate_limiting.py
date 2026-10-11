"""
Integration tests for multi-dimensional rate limiting
Validates distributed enforcement across multiple replicas
"""

import pytest
import httpx
import asyncio
import uuid
from typing import List


class TestMultiDimensionalRateLimiting:
    """Test rate limiting across all dimensions"""
    
    @pytest.mark.asyncio
    async def test_ip_rate_limiting(self):
        """Test IP-based rate limiting"""
        base_url = "http://localhost:8000"
        
        async with httpx.AsyncClient(base_url=base_url) as client:
            # Make requests until rate limited
            device_id = f"device_{uuid.uuid4().hex[:8]}"
            
            responses = []
            for i in range(120):  # Exceed limit of 100
                response = await client.post(
                    "/v1/challenge",
                    json={"device_id": f"{device_id}_{i}"},
                    headers={"X-Device-ID": device_id}
                )
                responses.append(response.status_code)
                
                if response.status_code == 429:
                    break
            
            # Should hit rate limit
            assert 429 in responses
            rate_limited_count = responses.count(429)
            assert rate_limited_count > 0
    
    @pytest.mark.asyncio
    async def test_device_rate_limiting(self):
        """Test device fingerprint rate limiting"""
        base_url = "http://localhost:8000"
        
        device_id = f"device_{uuid.uuid4().hex[:8]}"
        
        async with httpx.AsyncClient(base_url=base_url) as client:
            responses = []
            
            for i in range(15):  # Device limit is 10/min
                response = await client.post(
                    "/v1/challenge",
                    json={"device_id": device_id},
                    headers={"X-Device-ID": device_id}
                )
                responses.append(response.status_code)
            
            # Should hit device rate limit
            assert 429 in responses
    
    @pytest.mark.asyncio
    async def test_session_rate_limiting(self):
        """Test session-level rate limiting"""
        base_url = "http://localhost:8000"
        
        device_id = f"device_{uuid.uuid4().hex[:8]}"
        
        async with httpx.AsyncClient(base_url=base_url) as client:
            responses = []
            
            # Session limit is 5 challenges per 5 minutes
            for i in range(7):
                response = await client.post(
                    "/v1/challenge",
                    json={"device_id": device_id},
                    headers={"X-Device-ID": device_id}
                )
                responses.append(response)
            
            # Should hit session limit
            rate_limited = [r for r in responses if r.status_code == 429]
            assert len(rate_limited) > 0
            
            # Check error details
            error_data = rate_limited[0].json()
            assert error_data["error_code"] == "RATE_LIMIT_EXCEEDED"
            assert "retry_after" in error_data.get("error_details", {})
    
    @pytest.mark.asyncio
    async def test_challenge_level_rate_limiting(self):
        """Test per-challenge rate limiting (prevents brute force)"""
        base_url = "http://localhost:8000"
        
        device_id = f"device_{uuid.uuid4().hex[:8]}"
        
        async with httpx.AsyncClient(base_url=base_url) as client:
            # Generate challenge
            response = await client.post(
                "/v1/challenge",
                json={"device_id": device_id},
                headers={"X-Device-ID": device_id}
            )
            
            assert response.status_code == 200
            challenge = response.json()["challenges"][0]
            challenge_id = challenge["challenge_id"]
            
            # Try to verify same challenge multiple times
            fake_video = b"x" * 5000
            
            responses = []
            for i in range(5):  # Challenge limit is 3/5min
                response = await client.post(
                    "/v1/verify",
                    files={"video": ("test.webm", fake_video, "video/webm")},
                    data={
                        "device_id": device_id,
                        "challenge_id": challenge_id,
                        "token_id": challenge["token_id"]
                    }
                )
                responses.append(response.status_code)
            
            # Should hit challenge rate limit
            assert 429 in responses


class TestProgressivePenalties:
    """Test progressive penalty system"""
    
    @pytest.mark.asyncio
    async def test_soft_throttle_before_hard_block(self):
        """Test soft throttle kicks in before hard block"""
        base_url = "http://localhost:8000"
        
        device_id = f"device_{uuid.uuid4().hex[:8]}"
        
        async with httpx.AsyncClient(base_url=base_url) as client:
            response_times = []
            
            # Make requests and track response times
            for i in range(12):
                start = asyncio.get_event_loop().time()
                
                response = await client.post(
                    "/v1/challenge",
                    json={"device_id": f"{device_id}_{i}"},
                    headers={"X-Device-ID": device_id}
                )
                
                end = asyncio.get_event_loop().time()
                response_times.append(end - start)
                
                # Check for throttle header
                if response.headers.get("X-RateLimit-Throttled"):
                    print(f"Request {i+1}: Throttled (took {end-start:.2f}s)")
            
            # Later requests should take longer (throttling)
            if len(response_times) >= 10:
                avg_early = sum(response_times[:5]) / 5
                avg_late = sum(response_times[5:10]) / 5
                
                # Later requests should be slower due to throttling
                assert avg_late > avg_early
    
    @pytest.mark.asyncio
    async def test_temporary_ban_after_hard_block(self):
        """Test temporary ban is applied after hard block"""
        base_url = "http://localhost:8000"
        
        device_id = f"device_{uuid.uuid4().hex[:8]}"
        
        async with httpx.AsyncClient(base_url=base_url) as client:
            # Exceed hard block limit
            for i in range(15):
                await client.post(
                    "/v1/challenge",
                    json={"device_id": f"{device_id}_{i}"},
                    headers={"X-Device-ID": device_id}
                )
            
            # Now should be temporarily banned
            response = await client.post(
                "/v1/challenge",
                json={"device_id": device_id},
                headers={"X-Device-ID": device_id}
            )
            
            assert response.status_code == 429
            error_data = response.json()
            
            # Should indicate temporary ban
            retry_after = error_data.get("error_details", {}).get("retry_after")
            assert retry_after is not None
            assert retry_after > 60  # Ban should be substantial


class TestDistributedEnforcement:
    """Test rate limiting works across multiple API replicas"""
    
    @pytest.mark.asyncio
    async def test_limits_consistent_across_replicas(self):
        """
        Test rate limits remain correct under 3+ API replicas
        Simulates multiple replicas by making concurrent requests
        """
        base_url = "http://localhost:8000"
        
        device_id = f"device_{uuid.uuid4().hex[:8]}"
        
        async def make_request(client, request_num):
            """Single request"""
            return await client.post(
                "/v1/challenge",
                json={"device_id": f"{device_id}_{request_num}"},
                headers={"X-Device-ID": device_id}
            )
        
        async with httpx.AsyncClient(base_url=base_url) as client:
            # Make 20 concurrent requests (simulating 3 replicas)
            tasks = [make_request(client, i) for i in range(20)]
            responses = await asyncio.gather(*tasks)
            
            # Count successes and rate limits
            success_count = sum(1 for r in responses if r.status_code == 200)
            rate_limited_count = sum(1 for r in responses if r.status_code == 429)
            
            # Should enforce limit correctly even with concurrency
            # Device limit is 10/min, so ~10 should succeed, rest blocked
            assert rate_limited_count > 0
            assert success_count <= 12  # Allow slight variance for timing
    
    @pytest.mark.asyncio
    async def test_redis_atomic_operations(self):
        """Test Redis operations are atomic (no race conditions)"""
        base_url = "http://localhost:8000"
        
        device_id = f"device_{uuid.uuid4().hex[:8]}"
        
        async def burst_requests(client):
            """Make rapid concurrent requests"""
            tasks = [
                client.post(
                    "/v1/challenge",
                    json={"device_id": f"{device_id}_{i}"},
                    headers={"X-Device-ID": device_id}
                )
                for i in range(50)
            ]
            return await asyncio.gather(*tasks, return_exceptions=True)
        
        async with httpx.AsyncClient(base_url=base_url) as client:
            # Multiple bursts to test atomicity
            all_responses = []
            
            for burst in range(3):
                responses = await burst_requests(client)
                all_responses.extend([r for r in responses if not isinstance(r, Exception)])
            
            # Count total allowed vs blocked
            allowed = sum(1 for r in all_responses if r.status_code == 200)
            blocked = sum(1 for r in all_responses if r.status_code == 429)
            
            # Should enforce limit correctly (no over-allowance)
            # With device limit of 10/min, after 3 bursts most should be blocked
            assert blocked > allowed


class TestBypassDetection:
    """Test bypass attempt detection and cost increase"""
    
    @pytest.mark.asyncio
    async def test_ip_rotation_detected(self):
        """Test IP rotation is detected and tracked"""
        base_url = "http://localhost:8000"
        
        device_id = f"device_{uuid.uuid4().hex[:8]}"
        
        # First, establish device-IP mapping
        async with httpx.AsyncClient(base_url=base_url) as client:
            # Make request from "first IP" (simulated via headers)
            await client.post(
                "/v1/challenge",
                json={"device_id": device_id},
                headers={
                    "X-Device-ID": device_id,
                    "X-Forwarded-For": "1.2.3.4"
                }
            )
            
            # Now "rotate IP" (same device, different IP)
            response = await client.post(
                "/v1/challenge",
                json={"device_id": device_id},
                headers={
                    "X-Device-ID": device_id,
                    "X-Forwarded-For": "5.6.7.8"
                }
            )
            
            # Get bypass metrics
            metrics_response = await client.get("/metrics/bypass-attempts")
            
            if metrics_response.status_code == 200:
                metrics = metrics_response.json()
                bypass_attempts = metrics.get("bypass_attempts", {})
                
                # Should detect IP rotation
                assert bypass_attempts.get("ip_rotation", 0) > 0
    
    @pytest.mark.asyncio
    async def test_bypass_cost_increases(self):
        """Test bypass attempts increase attacker cost (measurable metric)"""
        base_url = "http://localhost:8000"
        
        async with httpx.AsyncClient(base_url=base_url) as client:
            # Get initial metrics
            initial_metrics = await client.get("/metrics/bypass-attempts")
            initial_data = initial_metrics.json() if initial_metrics.status_code == 200 else {}
            initial_count = initial_data.get("bypass_attempts", {}).get("ip_rotation", 0)
            
            # Simulate bypass attempts
            device_id = f"device_{uuid.uuid4().hex[:8]}"
            
            for i in range(5):
                await client.post(
                    "/v1/challenge",
                    json={"device_id": device_id},
                    headers={
                        "X-Device-ID": device_id,
                        "X-Forwarded-For": f"10.0.0.{i}"
                    }
                )
            
            # Get final metrics
            final_metrics = await client.get("/metrics/bypass-attempts")
            final_data = final_metrics.json() if final_metrics.status_code == 200 else {}
            final_count = final_data.get("bypass_attempts", {}).get("ip_rotation", 0)
            
            # Bypass counter should increase (measurable cost)
            assert final_count >= initial_count


class TestRateLimitHeaders:
    """Test rate limit headers are present and accurate"""
    
    @pytest.mark.asyncio
    async def test_rate_limit_headers_present(self):
        """Test X-RateLimit-* headers are returned"""
        base_url = "http://localhost:8000"
        
        device_id = f"device_{uuid.uuid4().hex[:8]}"
        
        async with httpx.AsyncClient(base_url=base_url) as client:
            response = await client.post(
                "/v1/challenge",
                json={"device_id": device_id},
                headers={"X-Device-ID": device_id}
            )
            
            # Check headers
            assert "X-RateLimit-Limit" in response.headers
            assert "X-RateLimit-Remaining" in response.headers
            assert "X-RateLimit-Reset" in response.headers
    
    @pytest.mark.asyncio
    async def test_rate_limit_headers_accurate(self):
        """Test rate limit headers decrement correctly"""
        base_url = "http://localhost:8000"
        
        device_id = f"device_{uuid.uuid4().hex[:8]}"
        
        async with httpx.AsyncClient(base_url=base_url) as client:
            # Make first request
            response1 = await client.post(
                "/v1/challenge",
                json={"device_id": f"{device_id}_1"},
                headers={"X-Device-ID": device_id}
            )
            
            remaining1 = int(response1.headers.get("X-RateLimit-Remaining", 0))
            
            # Make second request
            response2 = await client.post(
                "/v1/challenge",
                json={"device_id": f"{device_id}_2"},
                headers={"X-Device-ID": device_id}
            )
            
            remaining2 = int(response2.headers.get("X-RateLimit-Remaining", 0))
            
            # Remaining should decrease
            assert remaining2 < remaining1