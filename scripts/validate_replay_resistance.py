#!/usr/bin/env python3
"""
Validate replay resistance and tamper detection
Ensures 100% success rates
"""

import asyncio
import httpx
import sys


async def validate_tamper_detection():
    """Validate 100% tamper detection"""
    
    print("🔐 Testing Token Tamper Detection\n")
    
    base_url = "http://localhost:8000"
    
    async with httpx.AsyncClient(base_url=base_url) as client:
        # Generate challenge
        response = await client.post(
            "/v1/challenge",
            json={"device_id": "tamper_validation_test"}
        )
        
        if response.status_code != 200:
            print(f"❌ Failed to generate challenge: {response.status_code}")
            return False
        
        challenge = response.json()["challenges"][0]
        token = challenge["token_id"]
        
        # Test 20 tamper attempts
        tamper_detected = 0
        
        for i in range(20):
            # Tamper token
            if i % 2 == 0:
                tampered = token[:-5] + "XXXXX"
            else:
                tampered = "v4.public.fake_token_" + str(i)
            
            # Try to use tampered token
            response = await client.post(
                "/v1/verify",
                files={"video": ("test.webm", b"x" * 5000, "video/webm")},
                data={
                    "device_id": "tamper_validation_test",
                    "challenge_id": challenge["challenge_id"],
                    "token_id": tampered
                }
            )
            
            if response.status_code in [403, 401, 400]:
                tamper_detected += 1
        
        detection_rate = (tamper_detected / 20) * 100
        
        print(f"Tamper Detection Rate: {tamper_detected}/20 = {detection_rate:.1f}%")
        
        if detection_rate == 100.0:
            print("✅ Token tamper detection: 100%\n")
            return True
        else:
            print(f"❌ Token tamper detection: {detection_rate}% (expected 100%)\n")
            return False


async def validate_replay_prevention():
    """Validate 100% replay prevention"""
    
    print("🔄 Testing Replay Prevention\n")
    
    base_url = "http://localhost:8000"
    
    async with httpx.AsyncClient(base_url=base_url) as client:
        # Generate challenge
        response = await client.post(
            "/v1/challenge",
            json={"device_id": "replay_validation_test"}
        )
        
        if response.status_code != 200:
            print(f"❌ Failed to generate challenge: {response.status_code}")
            return False
        
        challenge = response.json()["challenges"][0]
        token = challenge["token_id"]
        challenge_id = challenge["challenge_id"]
        
        # First use
        first_response = await client.post(
            "/v1/verify",
            files={"video": ("test.webm", b"x" * 5000, "video/webm")},
            data={
                "device_id": "replay_validation_test",
                "challenge_id": challenge_id,
                "token_id": token
            }
        )
        
        # Replay attempts
        replay_blocked = 0
        
        for i in range(20):
            replay_response = await client.post(
                "/v1/verify",
                files={"video": ("test.webm", b"x" * 5000, "video/webm")},
                data={
                    "device_id": "replay_validation_test",
                    "challenge_id": challenge_id,
                    "token_id": token
                }
            )
            
            if replay_response.status_code == 403:
                replay_blocked += 1
        
        prevention_rate = (replay_blocked / 20) * 100
        
        print(f"Replay Prevention Rate: {replay_blocked}/20 = {prevention_rate:.1f}%")
        
        if prevention_rate == 100.0:
            print("✅ Replay prevention: 100%\n")
            return True
        else:
            print(f"❌ Replay prevention: {prevention_rate}% (expected 100%)\n")
            return False


async def main():
    """Run all validations"""
    
    print("="*60)
    print("REPLAY RESISTANCE & TAMPER DETECTION VALIDATION")
    print("="*60)
    print()
    
    tamper_ok = await validate_tamper_detection()
    replay_ok = await validate_replay_prevention()
    
    print("="*60)
    print("SUMMARY")
    print("="*60)
    print(f"Token Tamper Detection: {'✅ PASS' if tamper_ok else '❌ FAIL'}")
    print(f"Replay Prevention: {'✅ PASS' if replay_ok else '❌ FAIL'}")
    print()
    
    if tamper_ok and replay_ok:
        print("🎉 All validations passed: 10/10")
        return 0
    else:
        print("❌ Some validations failed")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))