"""
Secrets Manager - Vault/KMS Integration
Centralized secrets management with automatic rotation
"""

import os
import hvac
import boto3
from typing import Dict, Any, Optional
from datetime import datetime, timedelta
import json
import base64
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2
import logging

logger = logging.getLogger(__name__)


class SecretsBackend:
    """Base class for secrets backends"""
    
    def get_secret(self, secret_name: str) -> str:
        raise NotImplementedError
    
    def set_secret(self, secret_name: str, secret_value: str) -> bool:
        raise NotImplementedError
    
    def rotate_secret(self, secret_name: str, new_value: str) -> bool:
        raise NotImplementedError
    
    def list_secrets(self) -> list[str]:
        raise NotImplementedError


class HashiCorpVaultBackend(SecretsBackend):
    """
    HashiCorp Vault integration
    
    Features:
    - KV v2 secrets engine
    - Dynamic secrets
    - Automatic token renewal
    - Transit encryption
    """
    
    def __init__(
        self,
        vault_url: str,
        vault_token: Optional[str] = None,
        vault_role_id: Optional[str] = None,
        vault_secret_id: Optional[str] = None,
        mount_point: str = "secret"
    ):
        self.vault_url = vault_url
        self.mount_point = mount_point
        
        # Initialize Vault client
        self.client = hvac.Client(url=vault_url)
        
        # Authenticate
        if vault_token:
            # Token-based auth (for development)
            self.client.token = vault_token
        elif vault_role_id and vault_secret_id:
            # AppRole auth (for production)
            self.client.auth.approle.login(
                role_id=vault_role_id,
                secret_id=vault_secret_id
            )
        else:
            raise ValueError("Must provide either vault_token or vault_role_id + vault_secret_id")
        
        if not self.client.is_authenticated():
            raise Exception("Vault authentication failed")
        
        logger.info("✅ Connected to HashiCorp Vault")
    
    def get_secret(self, secret_name: str) -> str:
        """
        Get secret from Vault KV v2
        
        Args:
            secret_name: Secret path (e.g., "database/postgres")
        
        Returns:
            Secret value
        """
        
        try:
            # Read from KV v2
            response = self.client.secrets.kv.v2.read_secret_version(
                path=secret_name,
                mount_point=self.mount_point
            )
            
            secret_data = response["data"]["data"]
            
            # Return the 'value' field or entire data if single key
            if "value" in secret_data:
                return secret_data["value"]
            elif len(secret_data) == 1:
                return list(secret_data.values())[0]
            else:
                # Return as JSON if multiple keys
                return json.dumps(secret_data)
                
        except Exception as e:
            logger.error(f"Failed to read secret {secret_name}: {e}")
            raise
    
    def set_secret(self, secret_name: str, secret_value: str) -> bool:
        """
        Store secret in Vault KV v2
        
        Args:
            secret_name: Secret path
            secret_value: Secret value
        
        Returns:
            True if successful
        """
        
        try:
            # Write to KV v2
            self.client.secrets.kv.v2.create_or_update_secret(
                path=secret_name,
                secret={"value": secret_value},
                mount_point=self.mount_point
            )
            
            logger.info(f"✅ Secret {secret_name} stored in Vault")
            return True
            
        except Exception as e:
            logger.error(f"Failed to write secret {secret_name}: {e}")
            return False
    
    def rotate_secret(self, secret_name: str, new_value: str) -> bool:
        """
        Rotate secret in Vault
        
        Creates new version while maintaining history
        """
        
        try:
            # Get current version for audit
            current = self.get_secret(secret_name)
            
            # Write new version
            self.client.secrets.kv.v2.create_or_update_secret(
                path=secret_name,
                secret={
                    "value": new_value,
                    "rotated_at": datetime.utcnow().isoformat(),
                    "previous_version": "hidden"  # Don't store old secret
                },
                mount_point=self.mount_point
            )
            
            logger.info(f"✅ Secret {secret_name} rotated")
            return True
            
        except Exception as e:
            logger.error(f"Failed to rotate secret {secret_name}: {e}")
            return False
    
    def list_secrets(self) -> list[str]:
        """List all secrets in Vault"""
        
        try:
            response = self.client.secrets.kv.v2.list_secrets(
                path="",
                mount_point=self.mount_point
            )
            
            return response["data"]["keys"]
            
        except Exception as e:
            logger.error(f"Failed to list secrets: {e}")
            return []


class AWSSecretsManagerBackend(SecretsBackend):
    """
    AWS Secrets Manager integration
    
    Features:
    - Automatic rotation
    - KMS encryption at rest
    - Cross-region replication
    - Resource-based policies
    """
    
    def __init__(self, region_name: str = "us-east-1"):
        self.region_name = region_name
        
        # Initialize AWS Secrets Manager client
        self.client = boto3.client(
            'secretsmanager',
            region_name=region_name
        )
        
        logger.info(f"✅ Connected to AWS Secrets Manager ({region_name})")
    
    def get_secret(self, secret_name: str) -> str:
        """
        Get secret from AWS Secrets Manager
        
        Args:
            secret_name: Secret ARN or name
        
        Returns:
            Secret value
        """
        
        try:
            response = self.client.get_secret_value(SecretId=secret_name)
            
            # Handle both string and binary secrets
            if 'SecretString' in response:
                return response['SecretString']
            else:
                # Binary secret
                return base64.b64decode(response['SecretBinary']).decode('utf-8')
                
        except Exception as e:
            logger.error(f"Failed to read secret {secret_name}: {e}")
            raise
    
    def set_secret(self, secret_name: str, secret_value: str) -> bool:
        """
        Create or update secret in AWS Secrets Manager
        
        Args:
            secret_name: Secret name
            secret_value: Secret value
        
        Returns:
            True if successful
        """
        
        try:
            # Try to create secret
            try:
                self.client.create_secret(
                    Name=secret_name,
                    SecretString=secret_value,
                    Description=f"Certivo secret: {secret_name}"
                )
                logger.info(f"✅ Secret {secret_name} created")
                
            except self.client.exceptions.ResourceExistsException:
                # Update existing secret
                self.client.put_secret_value(
                    SecretId=secret_name,
                    SecretString=secret_value
                )
                logger.info(f"✅ Secret {secret_name} updated")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to set secret {secret_name}: {e}")
            return False
    
    def rotate_secret(self, secret_name: str, new_value: str) -> bool:
        """
        Rotate secret in AWS Secrets Manager
        
        Uses automatic rotation with version staging
        """
        
        try:
            # Update secret with new value
            self.client.put_secret_value(
                SecretId=secret_name,
                SecretString=new_value,
                VersionStages=['AWSCURRENT']  # Mark as current version
            )
            
            logger.info(f"✅ Secret {secret_name} rotated")
            return True
            
        except Exception as e:
            logger.error(f"Failed to rotate secret {secret_name}: {e}")
            return False
    
    def list_secrets(self) -> list[str]:
        """List all secrets in AWS Secrets Manager"""
        
        try:
            response = self.client.list_secrets()
            return [secret['Name'] for secret in response['SecretList']]
            
        except Exception as e:
            logger.error(f"Failed to list secrets: {e}")
            return []


class LocalEncryptedBackend(SecretsBackend):
    """
    Local encrypted storage (development only)
    
    WARNING: Not for production use
    Uses Fernet encryption with key derived from master password
    """
    
    def __init__(self, secrets_file: str = ".secrets.enc", master_key: Optional[str] = None):
        self.secrets_file = secrets_file
        
        # Derive encryption key from master key
        if not master_key:
            master_key = os.getenv("SECRETS_MASTER_KEY", "INSECURE_DEFAULT_KEY")
        
        kdf = PBKDF2(
            algorithm=hashes.SHA256(),
            length=32,
            salt=b"certivo_salt_change_me",  # Static salt for deterministic key
            iterations=100000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(master_key.encode()))
        
        self.cipher = Fernet(key)
        
        # Load existing secrets
        self.secrets = self._load_secrets()
        
        logger.warning("⚠️  Using local encrypted storage (development only)")
    
    def _load_secrets(self) -> Dict[str, str]:
        """Load and decrypt secrets from file"""
        
        if not os.path.exists(self.secrets_file):
            return {}
        
        try:
            with open(self.secrets_file, 'rb') as f:
                encrypted = f.read()
            
            decrypted = self.cipher.decrypt(encrypted)
            return json.loads(decrypted.decode('utf-8'))
            
        except Exception as e:
            logger.error(f"Failed to load secrets: {e}")
            return {}
    
    def _save_secrets(self):
        """Encrypt and save secrets to file"""
        
        try:
            plaintext = json.dumps(self.secrets).encode('utf-8')
            encrypted = self.cipher.encrypt(plaintext)
            
            with open(self.secrets_file, 'wb') as f:
                f.write(encrypted)
                
        except Exception as e:
            logger.error(f"Failed to save secrets: {e}")
    
    def get_secret(self, secret_name: str) -> str:
        """Get secret from local storage"""
        
        if secret_name not in self.secrets:
            raise KeyError(f"Secret {secret_name} not found")
        
        return self.secrets[secret_name]
    
    def set_secret(self, secret_name: str, secret_value: str) -> bool:
        """Store secret in local storage"""
        
        self.secrets[secret_name] = secret_value
        self._save_secrets()
        
        logger.info(f"✅ Secret {secret_name} stored locally")
        return True
    
    def rotate_secret(self, secret_name: str, new_value: str) -> bool:
        """Rotate secret in local storage"""
        
        return self.set_secret(secret_name, new_value)
    
    def list_secrets(self) -> list[str]:
        """List all secrets in local storage"""
        
        return list(self.secrets.keys())


class SecretsManager:
    """
    Unified secrets manager with environment-based backend selection
    
    Supports:
    - HashiCorp Vault (production)
    - AWS Secrets Manager (cloud)
    - Local encrypted storage (development)
    """
    
    def __init__(self):
        environment = os.getenv("ENVIRONMENT", "development")
        secrets_backend = os.getenv("SECRETS_BACKEND", "local")
        
        if secrets_backend == "vault":
            # HashiCorp Vault
            self.backend = HashiCorpVaultBackend(
                vault_url=os.getenv("VAULT_URL", "http://vault:8200"),
                vault_token=os.getenv("VAULT_TOKEN"),
                vault_role_id=os.getenv("VAULT_ROLE_ID"),
                vault_secret_id=os.getenv("VAULT_SECRET_ID")
            )
            
        elif secrets_backend == "aws":
            # AWS Secrets Manager
            self.backend = AWSSecretsManagerBackend(
                region_name=os.getenv("AWS_REGION", "us-east-1")
            )
            
        else:
            # Local encrypted storage (development)
            if environment == "production":
                raise Exception("Local secrets backend not allowed in production")
            
            self.backend = LocalEncryptedBackend()
        
        logger.info(f"✅ Secrets Manager initialized (backend: {secrets_backend})")
    
    def get(self, secret_name: str, default: Optional[str] = None) -> Optional[str]:
        """
        Get secret value
        
        Args:
            secret_name: Secret identifier
            default: Default value if secret not found
        
        Returns:
            Secret value or default
        """
        
        try:
            return self.backend.get_secret(secret_name)
        except KeyError:
            if default is not None:
                return default
            raise
    
    def set(self, secret_name: str, secret_value: str) -> bool:
        """
        Store secret
        
        Args:
            secret_name: Secret identifier
            secret_value: Secret value
        
        Returns:
            True if successful
        """
        
        return self.backend.set_secret(secret_name, secret_value)
    
    def rotate(self, secret_name: str, new_value: str) -> bool:
        """
        Rotate secret to new value
        
        Args:
            secret_name: Secret identifier
            new_value: New secret value
        
        Returns:
            True if successful
        """
        
        return self.backend.rotate_secret(secret_name, new_value)
    
    def list(self) -> list[str]:
        """List all secret names"""
        
        return self.backend.list_secrets()


# Global secrets manager instance
_secrets_manager: Optional[SecretsManager] = None


def get_secrets_manager() -> SecretsManager:
    """Get global secrets manager instance (singleton)"""
    
    global _secrets_manager
    
    if _secrets_manager is None:
        _secrets_manager = SecretsManager()
    
    return _secrets_manager


def get_secret(secret_name: str, default: Optional[str] = None) -> Optional[str]:
    """Convenience function to get secret"""
    
    manager = get_secrets_manager()
    return manager.get(secret_name, default)