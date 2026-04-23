"""
PASETO (Platform-Agnostic Security Tokens) Implementation
More secure alternative to JWT with built-in encryption and signing

PASETO v4.public - Public-key signed tokens
- Tamper-proof
- Non-repudiable
- Compact
"""

import pyseto
from pyseto import Key, KeyInterface
from typing import Dict, Any, Optional
from datetime import datetime, timedelta
import json
import secrets
import os


class PasetoTokenManager:
    """
    PASETO token manager for challenge tokens
    
    Advantages over JWT:
    - No algorithm confusion attacks
    - Built-in expiry validation
    - Simpler API
    - Cryptographically authenticated
    """
    
    def __init__(self, private_key_path: Optional[str] = None):
        """
        Initialize PASETO token manager
        
        Args:
            private_key_path: Path to Ed25519 private key (PEM format)
        """
        
        if private_key_path and os.path.exists(private_key_path):
            # Load existing key
            with open(private_key_path, 'rb') as f:
                self.private_key = Key.new(version=4, purpose="public", key=f.read())
        else:
            # Generate new Ed25519 key pair
            self.private_key = Key.new(version=4, purpose="public")
            
            # Save for persistence (optional)
            if private_key_path:
                with open(private_key_path, 'wb') as f:
                    f.write(self.private_key.to_paserk())
        
        # Extract public key for verification
        self.public_key = self.private_key
    
    def create_challenge_token(
        self,
        challenge_id: str,
        device_id: str,
        nonce: str,
        session_metadata: Dict[str, Any],
        ttl_seconds: int = 300
    ) -> str:
        """
        Create PASETO challenge token
        
        Args:
            challenge_id: Unique challenge identifier
            device_id: Device fingerprint
            nonce: Cryptographic nonce for replay protection
            session_metadata: Bound session metadata (IP, user-agent, timestamp, etc.)
            ttl_seconds: Token time-to-live in seconds
        
        Returns:
            PASETO token string (v4.public.*)
        """
        
        # Create payload
        now = datetime.utcnow()
        expires_at = now + timedelta(seconds=ttl_seconds)
        
        payload = {
            # Standard claims
            "iss": "certivo-challenge-service",
            "sub": challenge_id,
            "aud": "certivo-verification-service",
            "iat": int(now.timestamp()),
            "exp": int(expires_at.timestamp()),
            "nbf": int(now.timestamp()),
            "jti": nonce,  # Unique token ID (nonce)
            
            # Custom claims
            "device_id": device_id,
            "challenge_id": challenge_id,
            "nonce": nonce,
            
            # Cryptographically bound session metadata
            "session_metadata": {
                "ip_hash": session_metadata.get("ip_hash"),
                "user_agent_hash": session_metadata.get("user_agent_hash"),
                "screen_resolution": session_metadata.get("screen_resolution"),
                "timezone_offset": session_metadata.get("timezone_offset"),
                "language": session_metadata.get("language"),
                "platform": session_metadata.get("platform"),
                "timestamp": int(now.timestamp())
            },
            
            # One-time use flag
            "one_time_use": True,
            
            # Watermark seed (for dynamic overlays)
            "watermark_seed": secrets.token_hex(16)
        }
        
        # Create PASETO token (v4.public)
        token = pyseto.encode(
            self.private_key,
            payload,
            serializer=json
        )
        
        return token.decode('utf-8')
    
    def verify_and_decode_token(
        self,
        token: str,
        expected_device_id: Optional[str] = None,
        expected_session_metadata: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Verify and decode PASETO token
        
        Args:
            token: PASETO token string
            expected_device_id: Expected device ID for binding validation
            expected_session_metadata: Expected session metadata for binding validation
        
        Returns:
            Decoded payload if valid, None if invalid
        """
        
        try:
            # Decode and verify token
            decoded = pyseto.decode(
                self.public_key,
                token,
                deserializer=json
            )
            
            payload = decoded.payload
            
            # Check expiry (pyseto does this automatically, but double-check)
            exp = payload.get("exp")
            if exp and datetime.utcnow().timestamp() > exp:
                return None
            
            # Check not-before
            nbf = payload.get("nbf")
            if nbf and datetime.utcnow().timestamp() < nbf:
                return None
            
            # Verify device ID binding (if provided)
            if expected_device_id:
                token_device_id = payload.get("device_id")
                if token_device_id != expected_device_id:
                    return None
            
            # Verify session metadata binding (if provided)
            if expected_session_metadata:
                token_metadata = payload.get("session_metadata", {})
                
                # Verify IP hash matches
                if expected_session_metadata.get("ip_hash") != token_metadata.get("ip_hash"):
                    return None
                
                # Verify user agent hash matches
                if expected_session_metadata.get("user_agent_hash") != token_metadata.get("user_agent_hash"):
                    return None
            
            return payload
            
        except Exception as e:
            # Token invalid (signature failed, malformed, etc.)
            print(f"Token verification failed: {e}")
            return None
    
    def extract_watermark_seed(self, token: str) -> Optional[str]:
        """Extract watermark seed from token without full verification"""
        
        try:
            decoded = pyseto.decode(
                self.public_key,
                token,
                deserializer=json
            )
            return decoded.payload.get("watermark_seed")
        except:
            return None


def hash_session_attribute(value: str) -> str:
    """
    Hash session attribute for privacy-preserving binding
    
    Args:
        value: Attribute value to hash
    
    Returns:
        SHA256 hash (hex)
    """
    import hashlib
    return hashlib.sha256(value.encode('utf-8')).hexdigest()[:16]