#!/usr/bin/env python3
"""
Weekly UX Performance Report
"""

import asyncio
import asyncpg
from datetime import datetime, timedelta


async def generate_report():
    pool = await asyncpg.create_pool(
        "postgresql://certivo:certivo@localhost:5432/certivo"
    )
    
    print("="*60)
    print("WEEKLY UX PERFORMANCE REPORT")
    print(f"Week ending: {datetime.now().strftime('%Y-%m-%d')}")
    print("="*60)
    
    # Time-to-complete stats
    stats = await pool.fetchrow(
        "SELECT * FROM get_performance_stats(168)"  # 7 days
    )
    
    print(f"\n📊 Time-to-Complete:")
    print(f"  Sessions: {stats['total_sessions']}")
    print(f"  Median: {stats['median_ms']/1000:.1f}s")
    print(f"  Mean: {stats['mean_ms']/1000:.1f}s")
    print(f"  P95: {stats['p95_ms']/1000:.1f}s")
    print(f"  Target met: {'✅ YES' if stats['target_met'] else '❌ NO'}")
    
    # Abandonment rate
    async with pool.acquire() as conn:
        abandonment = await conn.fetchrow(
            """
            SELECT 
                COUNT(*) FILTER (WHERE abandonment = TRUE) as abandoned,
                COUNT(*) as total,
                (COUNT(*) FILTER (WHERE abandonment = TRUE)::FLOAT / COUNT(*)) * 100 as rate
            FROM performance_metrics
            WHERE session_start >= NOW() - INTERVAL '7 days'
            """
        )
    
    print(f"\n📉 Abandonment:")
    print(f"  Total sessions: {abandonment['total']}")
    print(f"  Abandoned: {abandonment['abandoned']}")
    print(f"  Rate: {abandonment['rate']:.1f}%")
    
    # Fallback usage
    async with pool.acquire() as conn:
        fallback = await conn.fetchrow(
            """
            SELECT 
                COUNT(*) FILTER (WHERE needs_fallback = TRUE) as fallback_used,
                COUNT(*) as total,
                (COUNT(*) FILTER (WHERE needs_fallback = TRUE)::FLOAT / COUNT(*)) * 100 as rate
            FROM accessibility_preferences
            WHERE created_at >= NOW() - INTERVAL '7 days'
            """
        )
    
    print(f"\n🔄 Fallback Usage:")
    print(f"  Sessions needing fallback: {fallback['fallback_used']}")
    print(f"  Fallback rate: {fallback['rate']:.1f}%")
    
    await pool.close()


if __name__ == "__main__":
    asyncio.run(generate_report())