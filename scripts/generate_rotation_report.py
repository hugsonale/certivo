#!/usr/bin/env python3
"""
Generate rotation report
"""

import asyncio
import sys
from datetime import datetime, timedelta
import json

sys.path.insert(0, 'services/shared')

import asyncpg


async def generate_report(output_file: str = "rotation_report.md"):
    """Generate rotation report"""
    
    print(f"📊 Generating rotation report...")
    
    postgres_pool = await asyncpg.create_pool(
        "postgresql://certivo:certivo@localhost:5432/certivo"
    )
    
    async with postgres_pool.acquire() as conn:
        # Get all rotations in last 90 days
        rotations = await conn.fetch(
            """
            SELECT key_type, key_name, status, rotated_at, error, metadata
            FROM key_rotations
            WHERE rotated_at > NOW() - INTERVAL '90 days'
            ORDER BY rotated_at DESC
            """
        )
    
    await postgres_pool.close()
    
    # Generate report
    report = []
    
    report.append("# Secret Rotation Report")
    report.append("")
    report.append(f"Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}")
    report.append("")
    
    report.append("## Summary")
    report.append("")
    
    total = len(rotations)
    successful = sum(1 for r in rotations if r['status'] == 'completed')
    failed = sum(1 for r in rotations if r['status'] == 'failed')
    
    report.append(f"- Total rotations (90 days): {total}")
    report.append(f"- Successful: {successful}")
    report.append(f"- Failed: {failed}")
    report.append(f"- Success rate: {(successful/total*100):.1f}%" if total > 0 else "- Success rate: N/A")
    report.append("")
    
    report.append("## Recent Rotations")
    report.append("")
    report.append("| Date | Key Type | Key Name | Status |")
    report.append("|------|----------|----------|--------|")
    
    for rotation in rotations[:20]:  # Last 20
        date = rotation['rotated_at'].strftime('%Y-%m-%d %H:%M')
        key_type = rotation['key_type']
        key_name = rotation['key_name']
        status = "✅" if rotation['status'] == 'completed' else "❌"
        
        report.append(f"| {date} | {key_type} | {key_name} | {status} |")
    
    report.append("")
    
    report.append("## Rotation Schedule")
    report.append("")
    report.append("| Secret Type | Frequency | Last Rotated | Next Due |")
    report.append("|-------------|-----------|--------------|----------|")
    
    # Calculate next due dates
    secret_types = {}
    for rotation in rotations:
        key_type = rotation['key_type']
        if key_type not in secret_types or rotation['rotated_at'] > secret_types[key_type]:
            secret_types[key_type] = rotation['rotated_at']
    
    schedules = {
        'database_password': 90,  # days
        'api_key': 30,
        'session_secret': 90,
        'encryption_key': 365
    }
    
    for key_type, last_rotated in secret_types.items():
        frequency_days = schedules.get(key_type, 90)
        next_due = last_rotated + timedelta(days=frequency_days)
        
        days_until = (next_due - datetime.utcnow()).days
        status = "⚠️ OVERDUE" if days_until < 0 else f"{days_until} days"
        
        report.append(
            f"| {key_type} | {frequency_days} days | "
            f"{last_rotated.strftime('%Y-%m-%d')} | "
            f"{next_due.strftime('%Y-%m-%d')} ({status}) |"
        )
    
    report.append("")
    
    # Failed rotations
    if failed > 0:
        report.append("## Failed Rotations")
        report.append("")
        
        failed_rotations = [r for r in rotations if r['status'] == 'failed']
        
        for rotation in failed_rotations:
            report.append(f"### {rotation['key_name']}")
            report.append(f"- Date: {rotation['rotated_at'].strftime('%Y-%m-%d %H:%M')}")
            report.append(f"- Error: {rotation['error']}")
            report.append("")
    
    # Write report
    report_text = "\n".join(report)
    
    with open(output_file, 'w') as f:
        f.write(report_text)
    
    print(f"✅ Report generated: {output_file}")
    
    return 0


if __name__ == "__main__":
    output = sys.argv[1] if len(sys.argv) > 1 else "rotation_report.md"
    sys.exit(asyncio.run(generate_report(output)))