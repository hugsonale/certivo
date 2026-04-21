#!/usr/bin/env python3
"""
Manual rate limit testing script
"""

import asyncio
import httpx
import time
from typing import List


async def test_rate_limit_enforcement():
    """Test rate limit enforcement"""
    
    print("🔬 Testing Rate Limit Enforcement\n")
    
    base_url = "http://localhost:8000"
    device_id = f"test_device_{int(time.time())}"
    
    async with httpx.AsyncClient(base_url=base_url) as client:
        # Test 1: IP rate limiting
        print("Test 1: IP Rate Limiting (100/min)")
        responses = []
        
        for i in range(110):
            response = await client.post(
                "/v1/challenge",
                json={"device_id": f"{device_id}_{i}"},
                headers={"X-Device-ID": device_id}
            )
            responses.append(response.status_code)
            
            if i % 20 == 0:
                print(f"  Requests sent: {i+1}")
        
        allowed = responses.count(200)
        blocked = responses.count(429)
        
        print(f"  ✅ Allowed: {allowed}, Blocked: {blocked}")
        print(f"  ✅ Limit enforced: {blocked > 0}\n")
        
        # Test 2: Progressive penalties
        print("Test 2: Progressive Penalties")
        
        # Check for throttle header
        throttled_responses = [
            await client.post(
                "/v1/challenge",
                json={"device_id": f"{device_id}_throttle_{i}"},
                headers={"X-Device-ID": f"throttle_test_{int(time.time())}"}
            )
            for i in range(8)
        ]
        
        throttled = sum(
            1 for r in throttled_responses 
            if r.headers.get("X-RateLimit-Throttled") == "true"
        )
        
        print(f"  ✅ Throttled requests: {throttled}")
        print(f"  ✅ Soft throttle active: {throttled > 0}\n")
        
        # Test 3: Bypass detection
        print("Test 3: Bypass Detection (IP Rotation)")
        
        device_id_bypass = f"bypass_test_{int(time.time())}"
        
        for ip_suffix in range(5):
            await client.post(
                "/v1/challenge",
                json={"device_id": device_id_bypass},
                headers={
                    "X-Device-ID": device_id_bypass,
                    "X-Forwarded-For": f"10.0.0.{ip_suffix}"
                }
            )
        
        metrics_response = await client.get("/metrics/bypass-attempts")
        
        if metrics_response.status_code == 200:
            metrics = metrics_response.json()
            bypass_count = metrics.get("bypass_attempts", {}).get("ip_rotation", 0)
            print(f"  ✅ Bypass attempts detected: {bypass_count}")
            print(f"  ✅ Cost tracking active: {bypass_count > 0}\n")
        else:
            print(f"  ⚠️  Metrics endpoint not available\n")


if __name__ == "__main__":
    asyncio.run(test_rate_limit_enforcement())