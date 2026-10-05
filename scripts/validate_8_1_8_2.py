#!/usr/bin/env python3
"""
Validate 8.1 Friction Management + 8.2 Clarity & Accessibility
"""

import asyncio
import asyncpg
import sys
import os


async def main():
    """Validate all acceptance criteria"""
    
    print("="*60)
    print("8.1 FRICTION MANAGEMENT + 8.2 ACCESSIBILITY VALIDATION")
    print("="*60)
    
    try:
        pool = await asyncpg.create_pool(
            "postgresql://certivo:certivo@localhost:5432/certivo"
        )
    except Exception as e:
        print(f"\n❌ Database connection failed: {e}")
        return 1
    
    # Check 1: Performance metrics table exists
    print("\n✓ Check 1: Performance Tracking")
    
    async with pool.acquire() as conn:
        table_exists = await conn.fetchval(
            """
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_name = 'performance_metrics'
            )
            """
        )
    
    print(f"  Performance metrics table: {table_exists}")
    
    # Check 2: Progressive trust configs loaded
    print("\n✓ Check 2: Progressive Trust")
    
    async with pool.acquire() as conn:
        config_count = await conn.fetchval(
            "SELECT COUNT(*) FROM progressive_trust_config"
        )
    
    print(f"  Risk level configs: {config_count}")
    
    # Check 3: Time-to-complete stats (if data exists)
    print("\n✓ Check 3: Time-to-Complete Performance")
    
    try:
        stats = await pool.fetchrow("SELECT * FROM get_performance_stats(24)")
        
        if stats and stats['total_sessions'] > 0:
            print(f"  Sessions: {stats['total_sessions']}")
            print(f"  Median: {stats['median_ms']/1000:.1f}s")
            print(f"  Target met: {stats['target_met']}")
        else:
            print("  ⚠️  No performance data yet (run user tests)")
    except Exception as e:
        print(f"  ⚠️  Stats not available: {e}")
    
    # Check 4: Frontend components exist
    print("\n✓ Check 4: Frontend Components")
    
    components = [
        "frontend/src/components/VerificationFlow.jsx",
        "frontend/src/components/CameraPreview.jsx",
        "frontend/src/components/FallbackOptions.jsx",
        "frontend/src/styles/verification.css"
    ]
    
    for component in components:
        exists = os.path.exists(component)
        print(f"  {component}: {exists}")
    
    # Check 5: Guidance system
    print("\n✓ Check 5: Guidance System")
    
    from guidance_system import GuidanceSystem, GuidancePhase
    
    guidance = GuidanceSystem()
    test_guidance = guidance.get_phase_guidance(GuidancePhase.INITIAL, "en")
    
    print(f"  Guidance messages: {bool(test_guidance.message)}")
    print(f"  ARIA labels: {bool(test_guidance.aria_label)}")
    
    # Check 6: Accessibility system
    print("\n✓ Check 6: Accessibility")
    
    from accessibility_manager import AccessibilityManager, FallbackMethod
    
    acc_mgr = AccessibilityManager()
    fallback_options = acc_mgr.get_fallback_options("camera_unavailable")
    
    print(f"  Fallback methods available: {len(fallback_options)}")
    
    await pool.close()
    
    # Summary
    print("\n" + "="*60)
    print("VALIDATION SUMMARY")
    print("="*60)
    
    checks = [
        ("Performance tracking implemented", table_exists),
        ("Progressive trust configured", config_count == 5),
        ("Guidance system working", bool(test_guidance.message)),
        ("Fallback options available", len(fallback_options) >= 3),
        ("Frontend components exist", all(os.path.exists(c) for c in components))
    ]
    
    all_pass = all(result for _, result in checks)
    
    for check, result in checks:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"  {status}  {check}")
    
    print("\n" + "="*60)
    print("MANUAL TESTING REQUIRED:")
    print("="*60)
    print("  [ ] User testing: 10+ users, median ≤20s")
    print("  [ ] Screen reader testing completed")
    print("  [ ] Mobile device testing completed")
    print("  [ ] Accessibility audit passed")
    print("="*60)
    
    if all_pass:
        print("\n✅ CODE VALIDATION PASSED")
        print("⚠️  Complete manual testing before production")
        return 0
    else:
        print("\n❌ SOME CHECKS FAILED")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))