#!/usr/bin/env python3
"""
Validate no wildcard storage access in production
"""

import asyncio
import asyncpg
from datetime import datetime
import sys

sys.path.insert(0, 'services/security')
from access_control_manager import AccessControlManager


async def main():
    """Validate no wildcards"""
    
    pool = await asyncpg.create_pool(
        "postgresql://certivo:certivo@localhost:5432/certivo"
    )
    
    manager = AccessControlManager(pool)
    
    print("=" * 60)
    print("WILDCARD VALIDATION")
    print("=" * 60)
    
    report = await manager.validate_no_wildcards()
    
    print(f"\nValidated: {report['validated_at']}")
    print(f"Users Checked: {report['total_users_checked']}")
    print(f"Violations Found: {report['violations_found']}")
    
    if report['compliant']:
        print("\n✅ COMPLIANT: No wildcard storage access found")
    else:
        print("\n❌ NON-COMPLIANT: Wildcard permissions detected")
        print("\nVIOLATIONS:")
        for violation in report['violations']:
            print(f"\n  User: {violation['user_email']}")
            print(f"  Role: {violation['role']}")
            print(f"  Wildcards: {', '.join(violation['wildcard_permissions'])}")
    
    await pool.close()
    
    return 0 if report['compliant'] else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))