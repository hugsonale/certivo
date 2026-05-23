"""
AWS KMS Key Management
Manage encryption keys for data at rest
"""

import aioboto3
from typing import Dict, Any, List, Optional
import logging

logger = logging.getLogger(__name__)


class KMSKeyManager:
    """
    AWS KMS Key Manager
    
    Manages encryption keys for:
    - Database encryption
    - S3 bucket encryption
    - Application secrets
    
    Features:
    - Automatic key rotation
    - Key policy management
    - Audit logging
    """
    
    def __init__(self, region: str = "us-east-1"):
        self.region = region
    
    async def create_master_key(
        self,
        key_alias: str,
        description: str,
        rotation_enabled: bool = True
    ) -> str:
        """
        Create KMS master key
        
        Args:
            key_alias: Key alias (e.g., "certivo-database-key")
            description: Key description
            rotation_enabled: Enable automatic rotation
        
        Returns:
            Key ID
        """
        
        session = aioboto3.Session()
        
        async with session.client('kms', region_name=self.region) as kms:
            # Create key
            response = await kms.create_key(
                Description=description,
                KeyUsage='ENCRYPT_DECRYPT',
                Origin='AWS_KMS',
                MultiRegion=False
            )
            
            key_id = response['KeyMetadata']['KeyId']
            
            # Create alias
            await kms.create_alias(
                AliasName=f"alias/{key_alias}",
                TargetKeyId=key_id
            )
            
            # Enable rotation if requested
            if rotation_enabled:
                await kms.enable_key_rotation(KeyId=key_id)
            
            logger.info(
                f"✅ KMS key created:\n"
                f"   Alias: {key_alias}\n"
                f"   Key ID: {key_id}\n"
                f"   Rotation: {'Enabled' if rotation_enabled else 'Disabled'}"
            )
            
            return key_id
    
    async def encrypt_data(
        self,
        key_alias: str,
        plaintext: bytes
    ) -> bytes:
        """
        Encrypt data with KMS key
        
        Args:
            key_alias: Key alias
            plaintext: Data to encrypt
        
        Returns:
            Encrypted data
        """
        
        session = aioboto3.Session()
        
        async with session.client('kms', region_name=self.region) as kms:
            response = await kms.encrypt(
                KeyId=f"alias/{key_alias}",
                Plaintext=plaintext
            )
            
            return response['CiphertextBlob']
    
    async def decrypt_data(
        self,
        ciphertext: bytes
    ) -> bytes:
        """
        Decrypt data with KMS
        
        Args:
            ciphertext: Encrypted data
        
        Returns:
            Decrypted data
        """
        
        session = aioboto3.Session()
        
        async with session.client('kms', region_name=self.region) as kms:
            response = await kms.decrypt(
                CiphertextBlob=ciphertext
            )
            
            return response['Plaintext']
    
    async def rotate_key(self, key_id: str):
        """
        Manually rotate KMS key
        
        Args:
            key_id: Key identifier
        """
        
        session = aioboto3.Session()
        
        async with session.client('kms', region_name=self.region) as kms:
            await kms.enable_key_rotation(KeyId=key_id)
            
            logger.info(f"🔄 Key rotation enabled for: {key_id}")
    
    async def get_key_status(self, key_alias: str) -> Dict[str, Any]:
        """
        Get key status and metadata
        
        Args:
            key_alias: Key alias
        
        Returns:
            Key status information
        """
        
        session = aioboto3.Session()
        
        async with session.client('kms', region_name=self.region) as kms:
            # Get key ID from alias
            alias_response = await kms.describe_key(
                KeyId=f"alias/{key_alias}"
            )
            
            key_id = alias_response['KeyMetadata']['KeyId']
            
            # Get rotation status
            rotation_response = await kms.get_key_rotation_status(
                KeyId=key_id
            )
            
            return {
                "key_id": key_id,
                "alias": key_alias,
                "state": alias_response['KeyMetadata']['KeyState'],
                "rotation_enabled": rotation_response['KeyRotationEnabled'],
                "created": alias_response['KeyMetadata']['CreationDate'].isoformat()
            }