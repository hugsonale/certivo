#!/usr/bin/env python3
"""
Verify secret rotation was successful
"""

import asyncio
import sys
import logging
from datetime import datetime, timedelta

sys.path.insert(0, 'services/shared')

from secrets_manager import get_secrets_manager
import asyncpg

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def verify_rotation():
    """Verify all secrets were rotated successfully"""
    
    logger.info("🔍 Verifying secret rotation...")
    
    secrets_manager = get_secrets_manager()
    
    # Connect to database
    postgres_pool = await asyncpg.create_pool(
        "postgresql://certivo:certivo@localhost:5432/certivo"
    )
    
    checks = {}
    
    # Check database password
    logger.info("📊 Checking database password...")
    try:
        # Try to connect with new password from Vault
        new_password = secrets_manager.get("production/database/password")
        
        test_conn = await asyncpg.connect(
            database="certivo",
            user="certivo",
            password=new_password,
            host="localhost"
        )
        await test_conn.close()
        
        checks['database_password'] = True
        logger.info("  ✅ Database password valid")
        
    except Exception as e:
        checks['database_password'] = False
        logger.error(f"  ❌ Database password invalid: {e}")
    
    # Check rotation timestamps
    logger.info("📅 Checking rotation timestamps...")
    
    async with postgres_pool.acquire() as conn:
        recent_rotations = await conn.fetch(
            """
            SELECT key_type, key_name, rotated_at, status
            FROM key_rotations
            WHERE rotated_at > NOW() - INTERVAL '24 hours'
            ORDER BY rotated_at DESC
            """
        )
        
        if recent_rotations:
            logger.info(f"  ✅ Found {len(recent_rotations)} recent rotations")
            
            for rotation in recent_rotations:
                logger.info(f"    - {rotation['key_type']}: {rotation['key_name']} ({rotation['status']})")
            
            checks['rotation_records'] = True
        else:
            logger.warning("  ⚠️  No recent rotations found")
            checks['rotation_records'] = False
    
    # Check API keys
    logger.info("🔑 Checking API keys...")
    api_keys = ["internal", "external_service_a", "external_service_b"]
    
    for key_name in api_keys:
        try:
            secret_path = f"production/api/{key_name}"
            key_value = secrets_manager.get(secret_path)
            
            if key_value and len(key_value) >= 32:
                checks[f'api_key_{key_name}'] = True
                logger.info(f"  ✅ API key {key_name} valid")
            else:
                checks[f'api_key_{key_name}'] = False
                logger.error(f"  ❌ API key {key_name} invalid or too short")
                
        except Exception as e:
            checks[f'api_key_{key_name}'] = False
            logger.error(f"  ❌ Failed to check API key {key_name}: {e}")
    
    # Check session secret
    logger.info("🎫 Checking session secret...")
    try:
        session_secret = secrets_manager.get("production/session/secret")
        
        if session_secret and len(session_secret) >= 32:
            checks['session_secret'] = True
            logger.info("  ✅ Session secret valid")
        else:
            checks['session_secret'] = False
            logger.error("  ❌ Session secret invalid or too short")
            
    except Exception as e:
        checks['session_secret'] = False
        logger.error(f"  ❌ Failed to check session secret: {e}")
    
    # Cleanup
    await postgres_pool.close()
    
    # Summary
    logger.info("")
    logger.info("=" * 60)
    logger.info("VERIFICATION SUMMARY")
    logger.info("=" * 60)
    
    total = len(checks)
    passed = sum(1 for v in checks.values() if v)
    failed = total - passed
    
    for check_name, passed_check in checks.items():
        status = "✅" if passed_check else "❌"
        logger.info(f"{status} {check_name}")
    
    logger.info("")
    logger.info(f"Total checks: {total}")
    logger.info(f"Passed: {passed}")
    logger.info(f"Failed: {failed}")
    
    if failed > 0:
        logger.error(f"❌ {failed} checks failed")
        return 1
    else:
        logger.info("✅ All checks passed")
        return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(verify_rotation()))