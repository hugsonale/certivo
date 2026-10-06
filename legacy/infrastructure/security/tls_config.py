"""
TLS Configuration Enforcement
Ensure TLS 1.2+ for all connections
"""

import ssl
from typing import Dict, Any
import logging

logger = logging.getLogger(__name__)


class TLSConfigManager:
    """
    TLS Configuration Manager
    
    Enforces TLS 1.2+ for all connections
    
    Acceptance Criteria:
    - All connections use TLS 1.2 or higher
    - Strong cipher suites only
    - Certificate validation enabled
    """
    
    # Minimum TLS version
    MIN_TLS_VERSION = ssl.TLSVersion.TLSv1_2
    
    # Allowed cipher suites (strong ciphers only)
    ALLOWED_CIPHERS = [
        "TLS_ECDHE_RSA_WITH_AES_256_GCM_SHA384",
        "TLS_ECDHE_RSA_WITH_AES_128_GCM_SHA256",
        "TLS_ECDHE_RSA_WITH_CHACHA20_POLY1305_SHA256",
        "TLS_ECDHE_ECDSA_WITH_AES_256_GCM_SHA384",
        "TLS_ECDHE_ECDSA_WITH_AES_128_GCM_SHA256",
    ]
    
    @classmethod
    def create_ssl_context(cls) -> ssl.SSLContext:
        """
        Create SSL context with secure settings
        
        Returns:
            Configured SSL context
        """
        
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        
        # Set minimum TLS version
        context.minimum_version = cls.MIN_TLS_VERSION
        
        # Set cipher suites
        context.set_ciphers(":".join(cls.ALLOWED_CIPHERS))
        
        # Enable certificate verification
        context.check_hostname = True
        context.verify_mode = ssl.CERT_REQUIRED
        
        # Load default CA certificates
        context.load_default_certs()
        
        logger.info(
            f"✅ TLS context created:\n"
            f"   Min version: TLS 1.2\n"
            f"   Certificate verification: Enabled\n"
            f"   Hostname verification: Enabled"
        )
        
        return context
    
    @classmethod
    def validate_tls_version(cls, version: str) -> bool:
        """
        Validate TLS version meets minimum requirement
        
        Args:
            version: TLS version string (e.g., "TLSv1.2")
        
        Returns:
            True if version is acceptable
        """
        
        acceptable_versions = ["TLSv1.2", "TLSv1.3"]
        
        is_acceptable = version in acceptable_versions
        
        if not is_acceptable:
            logger.error(
                f"❌ TLS version {version} not acceptable. "
                f"Minimum: TLS 1.2"
            )
        
        return is_acceptable
    
    @classmethod
    def get_postgres_ssl_params(cls) -> Dict[str, Any]:
        """
        Get PostgreSQL SSL parameters
        
        Returns:
            SSL parameters for asyncpg
        """
        
        return {
            "ssl": cls.create_ssl_context(),
            "server_hostname": "certivo-db.postgres.internal"
        }
    
    @classmethod
    def get_redis_ssl_params(cls) -> Dict[str, Any]:
        """
        Get Redis SSL parameters
        
        Returns:
            SSL parameters for redis
        """
        
        return {
            "ssl": True,
            "ssl_cert_reqs": ssl.CERT_REQUIRED,
            "ssl_check_hostname": True,
            "ssl_ca_certs": "/etc/ssl/certs/ca-certificates.crt"
        }