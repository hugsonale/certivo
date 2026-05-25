#!/usr/bin/env python3
"""
Generate quarterly access review report
"""

import asyncio
import asyncpg
from datetime import datetime
import sys

sys.path.insert(0, 'services/security')
from access_control_manager import AccessControlManager


async def main():
    """Generate access review report"""
    
    # Connect to database
    pool = await asyncpg.create_pool(
        "postgresql://certivo:certivo@localhost:5432/certivo"
    )
    
    # Create access manager
    manager = AccessControlManager(pool)
    
    # Generate report
    report = await manager.generate_quarterly_review_report()
    
    # Print report
    print("=" * 60)
    print("QUARTERLY ACCESS REVIEW REPORT")
    print("=" * 60)
    print(f"\nQuarter: {report['quarter']}")
    print(f"Generated: {report['report_date']}")
    print(f"\nTotal Active Users: {report['total_active_users']}")
    print(f"\nUsers Requiring Review: {report['requiring_review']['count']}")
    
    if report['requiring_review']['count'] > 0:
        print("\nUSERS REQUIRING REVIEW:")
        for user in report['requiring_review']['users']:
            print(f"\n  User: {user['user_email']}")
            print(f"  Role: {user['role']}")
            print(f"  Review Due: {user['review_due']}")
    
    print(f"\nRecently Reviewed: {report['recently_reviewed']['count']}")
    
    # Export to CSV
    import csv
    
    with open(f"access_review_{report['quarter'].replace(' ', '_')}.csv", 'w') as f:
        writer = csv.writer(f)
        writer.writerow(['User Email', 'Role', 'Review Due', 'Status'])
        
        for user in report['requiring_review']['users']:
            writer.writerow([
                user['user_email'],
                user['role'],
                user['review_due'],
                'NEEDS REVIEW'
            ])
    
    print(f"\n✅ Report exported to: access_review_{report['quarter'].replace(' ', '_')}.csv")
    
    await pool.close()


if __name__ == "__main__":
    asyncio.run(main())