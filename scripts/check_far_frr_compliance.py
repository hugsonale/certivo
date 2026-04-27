#!/usr/bin/env python3
"""
Check FAR/FRR compliance with policy thresholds
"""

import asyncio
import httpx
import sys


async def check_compliance():
    """Check FAR/FRR policy compliance"""
    
    print("📊 Checking FAR/FRR Policy Compliance\n")
    
    base_url = "http://localhost:8004"
    
    try:
        async with httpx.AsyncClient(base_url=base_url) as client:
            response = await client.get(
                "/metrics/policy-compliance",
                headers={"X-Internal-Token": "secret"}
            )
            
            if response.status_code != 200:
                print(f"❌ Failed to fetch compliance metrics: {response.status_code}")
                return 1
            
            data = response.json()
            
            compliance = data["compliance"]
            metrics = data["metrics"]
            policy = data["policy"]
            recommendations = data["recommendations"]
            
            print("Policy Thresholds:")
            print(f"  FAR threshold: {policy['far_threshold']*100:.1f}%")
            print(f"  FRR threshold: {policy['frr_threshold']*100:.1f}%")
            print(f"  Target EER: {policy['target_eer']*100:.1f}%")
            print()
            
            print("Current Metrics:")
            print(f"  FAR: {metrics['far']*100:.2f}%")
            print(f"  FRR: {metrics['frr']*100:.2f}%")
            print(f"  EER: {metrics['eer']*100:.2f}%")
            print(f"  Accuracy: {metrics['accuracy']*100:.2f}%")
            print()
            
            print("Compliance Status:")
            print(f"  FAR compliant: {'✅' if compliance['far_compliant'] else '❌'}")
            print(f"  FRR compliant: {'✅' if compliance['frr_compliant'] else '❌'}")
            print(f"  Overall: {'✅ PASS' if compliance['overall_compliant'] else '❌ FAIL'}")
            print()
            
            if recommendations:
                print("⚠️  Recommendations:")
                for rec in recommendations:
                    print(f"  - {rec['issue']}")
                    print(f"    Current: {rec['current']*100:.2f}%")
                    print(f"    Threshold: {rec['threshold']*100:.2f}%")
                    print(f"    Action: {rec['action']}")
                print()
            
            if compliance['overall_compliant']:
                print("✅ FAR/FRR within policy thresholds")
                return 0
            else:
                print("❌ FAR/FRR exceeds policy thresholds")
                return 1
                
    except Exception as e:
        print(f"❌ Error checking compliance: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(check_compliance()))