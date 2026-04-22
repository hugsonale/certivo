#!/usr/bin/env python3
"""
Validate challenge entropy meets >= 20 bits target
"""

import sys
import asyncio
import httpx


async def validate_entropy():
    """Validate entropy target"""
    
    print("🔬 Validating Challenge Entropy\n")
    
    base_url = "http://localhost:8000"
    
    async with httpx.AsyncClient(base_url=base_url) as client:
        # Test 100 sessions
        entropy_measurements = []
        below_target = []
        
        for i in range(100):
            response = await client.post(
                "/v1/challenge",
                json={"device_id": f"entropy_test_{i}"}
            )
            
            if response.status_code == 200:
                data = response.json()
                session_entropy = data.get("session_entropy_bits", 0)
                entropy_measurements.append(session_entropy)
                
                if session_entropy < 20.0:
                    below_target.append((i, session_entropy))
        
        # Calculate statistics
        if entropy_measurements:
            avg_entropy = sum(entropy_measurements) / len(entropy_measurements)
            min_entropy = min(entropy_measurements)
            max_entropy = max(entropy_measurements)
            
            print(f"📊 Entropy Statistics:")
            print(f"   Sessions tested: {len(entropy_measurements)}")
            print(f"   Average entropy: {avg_entropy:.2f} bits")
            print(f"   Minimum entropy: {min_entropy:.2f} bits")
            print(f"   Maximum entropy: {max_entropy:.2f} bits")
            print()
            
            # Validate target
            if below_target:
                print(f"❌ {len(below_target)} sessions below 20-bit target:")
                for session_num, entropy in below_target[:5]:
                    print(f"   Session {session_num}: {entropy:.2f} bits")
                return 1
            else:
                print(f"✅ All sessions meet >= 20-bit entropy target")
                print(f"✅ Average: {avg_entropy:.2f} bits")
                return 0
        else:
            print("❌ No entropy measurements collected")
            return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(validate_entropy()))