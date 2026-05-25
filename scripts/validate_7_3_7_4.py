#!/usr/bin/env python3
"""
Validate 7.3 Legal/Consent and 7.4 Security
"""

import asyncio
import asyncpg
import ssl
import sys
import os

sys.path.insert(0, 'services/security')
from access_control_manager import AccessControlManager


async def main():
    """Validate all acceptance criteria"""
    
    print("=" * 60)
    print("7.3 LEGAL & CONSENT + 7.4 SECURITY VALIDATION")
    print("=" * 60)
    
    # Connect to database
    try:
        pool = await asyncpg.create_pool(
            "postgresql://certivo:certivo@localhost:5432/certivo"
        )
    except Exception as e:
        print(f"\n❌ Database connection failed: {e}")
        return 1
    
    # Check 1: DPIA exists
    print("\n✓ Check 1: DPIA Completed")
    dpia_exists = os.path.exists("docs/DPIA_COMPLETED.md")
    print(f"  DPIA file exists: {dpia_exists}")
    
    if not dpia_exists:
        print("  ⚠️  WARNING: Complete DPIA before production!")
    
    # Check 2: Consent tables exist
    print("\n✓ Check 2: Consent System")
    
    async with pool.acquire() as conn:
        consent_table = await conn.fetchval(
            """
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_name = 'consent_records'
            )
            """
        )
    
    print(f"  Consent tables exist: {consent_table}")
    
    # Check 3: TLS configuration
    print("\n✓ Check 3: TLS 1.2+ Enforcement")
    
    from infrastructure.security.tls_config import TLSConfigManager
    
    context = TLSConfigManager.create_ssl_context()
    tls_valid = context.minimum_version == ssl.TLSVersion.TLSv1_2
    
    print(f"  TLS 1.2+ enforced: {tls_valid}")
    
    # Check 4: No wildcards
    print("\n✓ Check 4: No Wildcard Storage Access")
    
    manager = AccessControlManager(pool)
    wildcard_report = await manager.validate_no_wildcards()
    
    print(f"  Users checked: {wildcard_report['total_users_checked']}")
    print(f"  Violations: {wildcard_report['violations_found']}")
    print(f"  Compliant: {wildcard_report['compliant']}")
    
    # Check 5: Quarterly reviews scheduled
    print("\n✓ Check 5: Quarterly Access Reviews")
    
    users_needing_review = await manager.get_users_requiring_review()
    
    print(f"  Users requiring review: {len(users_needing_review)}")
    print(f"  Review process documented: {os.path.exists('docs/QUARTERLY_ACCESS_REVIEW_CHECKLIST.md')}")
    
    await pool.close()
    
    # Summary
    print("\n" + "=" * 60)
    print("VALIDATION SUMMARY")
    print("=" * 60)
    
    checks = [
        ("DPIA completed", dpia_exists),
        ("Consent system implemented", consent_table),
        ("TLS 1.2+ enforced", tls_valid),
        ("No wildcard storage access", wildcard_report['compliant']),
        ("Quarterly review process", os.path.exists('docs/QUARTERLY_ACCESS_REVIEW_CHECKLIST.md'))
    ]
    
    all_pass = all(result for _, result in checks)
    
    for check, result in checks:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"  {status}  {check}")
    
    print("=" * 60)
    
    if all_pass:
        print("✅ ALL CHECKS PASSED - READY FOR PRODUCTION")
        return 0
    else:
        print("⚠️  SOME CHECKS FAILED - COMPLETE BEFORE PRODUCTION")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))