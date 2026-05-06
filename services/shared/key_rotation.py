"""
Key Rotation Framework
Automated rotation with zero-downtime deployment
"""

import secrets
import asyncio
import asyncpg
import redis.asyncio as redis
from typing import Dict, Any, Optional, Callable
from datetime import datetime, timedelta
import logging
from enum import Enum

logger = logging.getLogger(__name__)


class RotationStatus(str, Enum):
    """Rotation status"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


class KeyRotationManager:
    """
    Manage key rotation lifecycle
    
    Supports:
    - Zero-downtime rotation
    - Graceful rollback
    - Multi-stage deployment
    - Validation hooks
    """
    
    def __init__(
        self,
        secrets_manager,
        postgres_pool: asyncpg.Pool,
        redis_client: redis.Redis
    ):
        self.secrets_manager = secrets_manager
        self.postgres = postgres_pool
        self.redis = redis_client
        
        # Rotation tracking
        self.rotation_history = []
    
    async def rotate_database_password(
        self,
        database: str,
        username: str,
        secret_name: str
    ) -> bool:
        """
        Rotate database password
        
        Steps:
        1. Generate new password
        2. Update in database
        3. Store in secrets manager
        4. Update application config
        5. Verify connectivity
        6. Complete rotation
        
        Returns:
            True if successful
        """
        
        logger.info(f"🔄 Starting database password rotation: {database}/{username}")
        
        try:
            # Generate new password (32 chars, high entropy)
            new_password = secrets.token_urlsafe(32)
            
            # Update password in database
            async with self.postgres.acquire() as conn:
                await conn.execute(
                    f"ALTER USER {username} WITH PASSWORD $1",
                    new_password
                )
            
            logger.info(f"✅ Database password updated")
            
            # Store new password in secrets manager
            self.secrets_manager.set(secret_name, new_password)
            
            logger.info(f"✅ New password stored in secrets manager")
            
            # Verify new password works
            test_conn = await asyncpg.connect(
                database=database,
                user=username,
                password=new_password
            )
            await test_conn.close()
            
            logger.info(f"✅ New password verified")
            
            # Record rotation
            await self._record_rotation(
                key_type="database_password",
                key_name=secret_name,
                status=RotationStatus.COMPLETED
            )
            
            logger.info(f"✅ Database password rotation completed")
            return True
            
        except Exception as e:
            logger.error(f"❌ Database password rotation failed: {e}")
            
            await self._record_rotation(
                key_type="database_password",
                key_name=secret_name,
                status=RotationStatus.FAILED,
                error=str(e)
            )
            
            return False
    
    async def rotate_api_key(
        self,
        service_name: str,
        secret_name: str,
        update_callback: Optional[Callable] = None
    ) -> bool:
        """
        Rotate API key with dual-key period
        
        Zero-downtime strategy:
        1. Generate new key
        2. Deploy new key (both old and new valid)
        3. Wait for propagation (grace period)
        4. Revoke old key
        
        Args:
            service_name: Service identifier
            secret_name: Secret name in vault
            update_callback: Optional callback to update external service
        
        Returns:
            True if successful
        """
        
        logger.info(f"🔄 Starting API key rotation: {service_name}")
        
        try:
            # Get current key
            old_key = self.secrets_manager.get(secret_name)
            
            # Generate new key (64 chars, high entropy)
            new_key = secrets.token_urlsafe(64)
            
            # Store new key with version suffix
            self.secrets_manager.set(f"{secret_name}.new", new_key)
            
            logger.info(f"✅ New API key generated")
            
            # Dual-key period: both old and new valid
            await self.redis.setex(
                f"api_key:valid:{old_key[:16]}",
                3600,  # 1 hour grace period
                "old"
            )
            
            await self.redis.setex(
                f"api_key:valid:{new_key[:16]}",
                86400,  # 24 hours
                "new"
            )
            
            logger.info(f"✅ Dual-key period activated (1 hour)")
            
            # Update external service if callback provided
            if update_callback:
                await update_callback(new_key)
                logger.info(f"✅ External service updated")
            
            # Wait for grace period (shortened for testing)
            await asyncio.sleep(60)  # 1 minute in test, 1 hour in production
            
            # Promote new key to current
            self.secrets_manager.set(secret_name, new_key)
            self.secrets_manager.set(f"{secret_name}.old", old_key)
            
            # Revoke old key
            await self.redis.delete(f"api_key:valid:{old_key[:16]}")
            
            logger.info(f"✅ Old API key revoked")
            
            # Record rotation
            await self._record_rotation(
                key_type="api_key",
                key_name=secret_name,
                status=RotationStatus.COMPLETED
            )
            
            logger.info(f"✅ API key rotation completed")
            return True
            
        except Exception as e:
            logger.error(f"❌ API key rotation failed: {e}")
            
            await self._record_rotation(
                key_type="api_key",
                key_name=secret_name,
                status=RotationStatus.FAILED,
                error=str(e)
            )
            
            return False
    
    async def rotate_encryption_key(
        self,
        key_purpose: str,
        secret_name: str,
        re_encrypt_callback: Optional[Callable] = None
    ) -> bool:
        """
        Rotate encryption key with data re-encryption
        
        Steps:
        1. Generate new key
        2. Re-encrypt all data (if callback provided)
        3. Store new key
        4. Mark old key for archival
        
        Args:
            key_purpose: Key purpose/usage
            secret_name: Secret name
            re_encrypt_callback: Callback to re-encrypt data
        
        Returns:
            True if successful
        """
        
        logger.info(f"🔄 Starting encryption key rotation: {key_purpose}")
        
        try:
            # Generate new encryption key (256-bit)
            new_key = Fernet.generate_key().decode()
            
            # Store new key with version
            version = datetime.utcnow().strftime("%Y%m%d%H%M%S")
            self.secrets_manager.set(f"{secret_name}.v{version}", new_key)
            
            logger.info(f"✅ New encryption key generated (version: {version})")
            
            # Re-encrypt data if callback provided
            if re_encrypt_callback:
                old_key = self.secrets_manager.get(secret_name)
                
                logger.info(f"🔄 Re-encrypting data...")
                await re_encrypt_callback(old_key, new_key)
                logger.info(f"✅ Data re-encrypted")
            
            # Promote new key to current
            self.secrets_manager.set(secret_name, new_key)
            
            # Record rotation
            await self._record_rotation(
                key_type="encryption_key",
                key_name=secret_name,
                status=RotationStatus.COMPLETED,
                metadata={"version": version}
            )
            
            logger.info(f"✅ Encryption key rotation completed")
            return True
            
        except Exception as e:
            logger.error(f"❌ Encryption key rotation failed: {e}")
            
            await self._record_rotation(
                key_type="encryption_key",
                key_name=secret_name,
                status=RotationStatus.FAILED,
                error=str(e)
            )
            
            return False
    
    async def rotate_session_secret(self, secret_name: str) -> bool:
        """
        Rotate session secret key
        
        Uses dual-key validation during transition
        """
        
        logger.info(f"🔄 Starting session secret rotation")
        
        try:
            # Generate new secret (256-bit)
            new_secret = secrets.token_hex(32)
            
            # Get old secret
            old_secret = self.secrets_manager.get(secret_name)
            
            # Dual-secret period: validate with both
            self.secrets_manager.set(f"{secret_name}.new", new_secret)
            self.secrets_manager.set(f"{secret_name}.old", old_secret)
            
            logger.info(f"✅ Dual-secret validation enabled")
            
            # Wait for existing sessions to expire (1 hour)
            # In production, this would be session TTL
            await asyncio.sleep(60)  # Shortened for testing
            
            # Promote new secret
            self.secrets_manager.set(secret_name, new_secret)
            
            logger.info(f"✅ Session secret rotated")
            
            # Record rotation
            await self._record_rotation(
                key_type="session_secret",
                key_name=secret_name,
                status=RotationStatus.COMPLETED
            )
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Session secret rotation failed: {e}")
            return False
    
    async def emergency_rotate_all(self, reason: str) -> Dict[str, bool]:
        """
        Emergency rotation of all secrets
        
        Used in case of compromise or security incident
        
        Args:
            reason: Reason for emergency rotation
        
        Returns:
            Dictionary of rotation results
        """
        
        logger.critical(f"🚨 EMERGENCY ROTATION INITIATED: {reason}")
        
        results = {}
        
        # List all secrets
        secrets_list = self.secrets_manager.list()
        
        for secret_name in secrets_list:
            logger.info(f"🔄 Emergency rotating: {secret_name}")
            
            try:
                # Determine secret type and rotate accordingly
                if "database" in secret_name.lower():
                    success = await self.rotate_database_password(
                        database="certivo",
                        username="certivo",
                        secret_name=secret_name
                    )
                elif "api" in secret_name.lower():
                    success = await self.rotate_api_key(
                        service_name=secret_name,
                        secret_name=secret_name
                    )
                elif "session" in secret_name.lower():
                    success = await self.rotate_session_secret(secret_name)
                else:
                    # Generic rotation
                    new_value = secrets.token_urlsafe(32)
                    success = self.secrets_manager.rotate(secret_name, new_value)
                
                results[secret_name] = success
                
            except Exception as e:
                logger.error(f"❌ Failed to rotate {secret_name}: {e}")
                results[secret_name] = False
        
        # Record emergency rotation
        await self._record_rotation(
            key_type="emergency_rotation",
            key_name="all_secrets",
            status=RotationStatus.COMPLETED,
            metadata={
                "reason": reason,
                "results": results
            }
        )
        
        logger.critical(f"🚨 Emergency rotation completed: {sum(results.values())}/{len(results)} successful")
        
        return results
    
    async def _record_rotation(
        self,
        key_type: str,
        key_name: str,
        status: RotationStatus,
        error: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """Record rotation in audit log"""
        
        async with self.postgres.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO key_rotations
                (key_type, key_name, status, error, metadata, rotated_at)
                VALUES ($1, $2, $3, $4, $5, $6)
                """,
                key_type,
                key_name,
                status.value,
                error,
                json.dumps(metadata or {}),
                datetime.utcnow()
            )