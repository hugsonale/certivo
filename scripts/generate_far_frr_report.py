#!/usr/bin/env python3
"""
Generate comprehensive FAR/FRR report
"""

import asyncio
import httpx
import sys
from datetime import datetime


async def generate_report():
    """Generate FAR/FRR report"""
    
    base_url = "http://localhost:8004"
    
    print("# FAR/FRR Performance Report")
    print()
    print(f"Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print()
    
    try:
        async with httpx.AsyncClient(base_url=base_url) as client:
            # Get current metrics
            response = await client.get(
                "/metrics/far-frr?time_window_hours=24",
                headers={"X-Internal-Token": "secret"}
            )
            
            if response.status_code == 200:
                metrics = response.json()
                
                print("## 24-Hour Metrics")
                print()
                print(f"- **FAR (False Acceptance Rate):** {metrics['far']*100:.3f}%")
                print(f"- **FRR (False Rejection Rate):** {metrics['frr']*100:.3f}%")
                print(f"- **EER (Equal Error Rate):** {metrics['eer']*100:.3f}%")
                print(f"- **Accuracy:** {metrics['accuracy']*100:.2f}%")
                print()
                
                counts = metrics['counts']
                print("## Verification Counts")
                print()
                print(f"- True Accept: {counts['true_accept']}")
                print(f"- False Reject: {counts['false_reject']}")
                print(f"- False Accept: {counts['false_accept']}")
                print(f"- True Reject: {counts['true_reject']}")
                print(f"- **Total:** {counts['total']}")
                print()
            
            # Get performance trend
            response = await client.get(
                "/metrics/performance-trend?days=7",
                headers={"X-Internal-Token": "secret"}
            )
            
            if response.status_code == 200:
                trend_data = response.json()
                trends = trend_data['trends']
                
                print("## 7-Day Trend")
                print()
                print("| Date | FAR | FRR | Verifications |")
                print("|------|-----|-----|---------------|")
                
                for day in trends:
                    print(f"| {day['date']} | {day['far']*100:.2f}% | {day['frr']*100:.2f}% | {day['total_verifications']} |")
                
                print()
            
            # Get policy compliance
            response = await client.get(
                "/metrics/policy-compliance",
                headers={"X-Internal-Token": "secret"}
            )
            
            if response.status_code == 200:
                compliance_data = response.json()
                compliance = compliance_data['compliance']
                
                print("## Policy Compliance")
                print()
                print(f"- FAR Compliant: {'✅ Yes' if compliance['far_compliant'] else '❌ No'}")
                print(f"- FRR Compliant: {'✅ Yes' if compliance['frr_compliant'] else '❌ No'}")
                print(f"- Overall: {'✅ PASS' if compliance['overall_compliant'] else '❌ FAIL'}")
                print()
                
                if compliance_data.get('recommendations'):
                    print("## Recommendations")
                    print()
                    for rec in compliance_data['recommendations']:
                        print(f"### {rec['issue']}")
                        print(f"- Current: {rec['current']*100:.2f}%")
                        print(f"- Threshold: {rec['threshold']*100:.2f}%")
                        print(f"- **Action:** {rec['action']}")
                        print()
        
        return 0
        
    except Exception as e:
        print(f"Error generating report: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(generate_report()))