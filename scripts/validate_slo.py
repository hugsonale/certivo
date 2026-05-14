#!/usr/bin/env python3
"""
Validate SLO Acceptance Criteria
"""

import asyncio
import asyncpg
import redis.asyncio as redis
import sys
import os

sys.path.insert(0, 'services/shared')

from slo_monitor import SLOMonitor


async def main():
    """Validate SLO acceptance criteria"""
    
    print("="*60)
    print("SLO VALIDATION")
    print("="*60)
    
    postgres_pool = await asyncpg.create_pool(
        "postgresql://certivo:certivo@localhost:5432/certivo"
    )
    
    redis_client = await redis.from_url("redis://localhost:6379")
    
    monitor = SLOMonitor(postgres_pool, redis_client)
    
    # Generate SLO dashboard
    dashboard = await monitor.generate_slo_dashboard()
    
    print(f"\n📊 SLO Dashboard:")
    print(f"   Overall Status: {dashboard['overall_status']}")
    print(f"   Generated: {dashboard['generated_at']}")
    
    # Check each SLO
    print(f"\n✓ SLO Reports:")
    
    reports = dashboard['slo_reports']
    
    # API Availability
    availability = reports['api_availability']
    print(f"\n  1. API Availability:")
    print(f"     Target: {availability['target_value']}%")
    print(f"     Actual: {availability['actual_value']:.3f}%")
    print(f"     Status: {availability['status']}")
    print(f"     {'✅ PASS' if availability['status'] == 'healthy' else '❌ FAIL'}")
    
    # Challenge Issuance
    challenge = reports['challenge_issuance_latency']
    print(f"\n  2. Challenge Issuance (P95):")
    print(f"     Target: {challenge['target_value']}ms")
    print(f"     Actual: {challenge['actual_value']:.1f}ms")
    print(f"     Status: {challenge['status']}")
    print(f"     {'✅ PASS' if challenge['status'] == 'healthy' else '❌ FAIL'}")
    
    # Verify Accept
    verify = reports['verify_accept_latency']
    print(f"\n  3. Verify Accept (P95, excluding upload):")
    print(f"     Target: {verify['target_value']}ms")
    print(f"     Actual: {verify['actual_value']:.1f}ms")
    print(f"     Status: {verify['status']}")
    print(f"     {'✅ PASS' if verify['status'] == 'healthy' else '❌ FAIL'}")
    
    # Queue Processing
    queue = reports['queue_processing_delay']
    print(f"\n  4. Queue Processing (P95):")
    print(f"     Target: {queue['target_value']}ms")
    print(f"     Actual: {queue['actual_value']:.1f}ms")
    print(f"     Status: {queue['status']}")
    print(f"     {'✅ PASS' if queue['status'] == 'healthy' else '❌ FAIL'}")
    
    # Summary
    print("\n" + "="*60)
    print("VALIDATION SUMMARY")
    print("="*60)
    
    all_healthy = all(
        r['status'] == 'healthy'
        for r in reports.values()
    )
    
    print(f"  Overall: {'✅ ALL SLOs MET' if all_healthy else '⚠️  SOME SLOs AT RISK'}")
    print(f"  Healthy: {dashboard['summary']['healthy']}/{dashboard['summary']['total_slos']}")
    print("="*60)
    
    await postgres_pool.close()
    await redis_client.close()
    
    return 0 if all_healthy else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))