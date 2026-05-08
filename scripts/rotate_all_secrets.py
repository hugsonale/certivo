#!/usr/bin/env python3
"""
Automated Secret Rotation Script
Rotates all secrets according to policy
"""

import asyncio
import sys
import argparse
from datetime import datetime
import logging

# Add shared modules to path
sys.path.insert(0, 'services/shared')

from secrets_manager import get_secrets_manager
from key_rotation import KeyRotationManager
import asyncpg
import redis.asyncio as redis

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def rotate_all_secrets(dry_run: bool = False):
    """
    Rotate all secrets according to policy
    
    Args:
        dry_run: If True, only simulate rotation without making changes
    """
    
    logger.info("🔄 Starting automated secret rotation")
    
    if dry_run:
        logger.info("⚠️  DRY RUN MODE - No changes will be made")
    
    # Initialize managers
    secrets_manager = get_secrets_manager()
    
    postgres_pool = await asyncpg.create_pool(
        "postgresql://certivo:certivo@localhost:5432/certivo"
    )
    
    redis_client = await redis.from_url("redis://localhost:6379")
    
    rotation_manager = KeyRotationManager(
        secrets_manager,
        postgres_pool,
        redis_client
    )
    
    results = {}
    
    # Rotate database passwords
    logger.info("📊 Rotating database passwords...")
    if not dry_run:
        results['database_password'] = await rotation_manager.rotate_database_password(
            database="certivo",
            username="certivo",
            secret_name="production/database/password"
        )
    else:
        logger.info("  [DRY RUN] Would rotate database password")
        results['database_password'] = True
    
    # Rotate API keys
    logger.info("🔑 Rotating API keys...")
    api_keys = ["internal", "external_service_a", "external_service_b"]
    
    for key_name in api_keys:
        if not dry_run:
            results[f'api_key_{key_name}'] = await rotation_manager.rotate_api_key(
                service_name=key_name,
                secret_name=f"production/api/{key_name}"
            )
        else:
            logger.info(f"  [DRY RUN] Would rotate API key: {key_name}")
            results[f'api_key_{key_name}'] = True
    
    # Rotate session secret
    logger.info("🎫 Rotating session secret...")
    if not dry_run:
        results['session_secret'] = await rotation_manager.rotate_session_secret(
            secret_name="production/session/secret"
        )
    else:
        logger.info("  [DRY RUN] Would rotate session secret")
        results['session_secret'] = True
    
    # Cleanup
    await postgres_pool.close()
    await redis_client.close()
    
    # Summary
    logger.info("")
    logger.info("=" * 60)
    logger.info("ROTATION SUMMARY")
    logger.info("=" * 60)
    
    total = len(results)
    successful = sum(1 for v in results.values() if v)
    failed = total - successful
    
    for secret_name, success in results.items():
        status = "✅" if success else "❌"
        logger.info(f"{status} {secret_name}")
    
    logger.info("")
    logger.info(f"Total: {total}")
    logger.info(f"Successful: {successful}")
    logger.info(f"Failed: {failed}")
    
    if failed > 0:
        logger.error(f"❌ {failed} rotations failed")
        return 1
    else:
        logger.info("✅ All rotations completed successfully")
        return 0


async def emergency_rotate(reason: str):
    """
    Emergency rotation of all secrets
    
    Args:
        reason: Reason for emergency rotation
    """
    
    logger.critical(f"🚨 EMERGENCY ROTATION INITIATED")
    logger.critical(f"Reason: {reason}")
    
    secrets_manager = get_secrets_manager()
    
    postgres_pool = await asyncpg.create_pool(
        "postgresql://certivo:certivo@localhost:5432/certivo"
    )
    
    redis_client = await redis.from_url("redis://localhost:6379")
    
    rotation_manager = KeyRotationManager(
        secrets_manager,
        postgres_pool,
        redis_client
    )
    
    # Emergency rotate all
    results = await rotation_manager.emergency_rotate_all(reason)
    
    # Cleanup
    await postgres_pool.close()
    await redis_client.close()
    
    # Summary
    successful = sum(1 for v in results.values() if v)
    total = len(results)
    
    logger.critical(f"Emergency rotation completed: {successful}/{total} successful")
    
    if successful < total:
        return 1
    else:
        return 0


def main():
    """Main entry point"""
    
    parser = argparse.ArgumentParser(description="Automated secret rotation")
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help="Simulate rotation without making changes"
    )
    parser.add_argument(
        '--emergency',
        action='store_true',
        help="Emergency rotation (all secrets immediately)"
    )
    parser.add_argument(
        '--reason',
        type=str,
        help="Reason for emergency rotation"
    )
    
    args = parser.parse_args()
    
    if args.emergency:
        if not args.reason:
            print("Error: --reason required for emergency rotation")
            return 1
        
        return asyncio.run(emergency_rotate(args.reason))
    else:
        return asyncio.run(rotate_all_secrets(dry_run=args.dry_run))


if __name__ == "__main__":
    sys.exit(main())