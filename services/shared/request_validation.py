"""
Strict Request Schema Validation
Zero-tolerance for malformed or malicious input
"""

from pydantic import BaseModel, Field, validator, ValidationError
from typing import Optional, Dict, Any, List
import re
from datetime import datetime


class StrictBaseModel(BaseModel):
    """
    Base model with strict validation
    
    Features:
    - No extra fields allowed
    - Strict type checking
    - Custom validators for common attacks
    """
    
    class Config:
        extra = "forbid"  # Reject unknown fields
        str_strip_whitespace = True  # Strip whitespace
        str_min_length = 1  # No empty strings
        validate_assignment = True  # Validate on assignment


class DeviceIDValidator:
    """Validator for device IDs"""
    
    @staticmethod
    def validate(value: str) -> str:
        """
        Validate device ID
        
        Rules:
        - Alphanumeric + underscore + hyphen only
        - Length: 8-64 characters
        - No SQL injection patterns
        - No path traversal patterns
        """
        
        if not value:
            raise ValueError("Device ID cannot be empty")
        
        # Length check
        if not (8 <= len(value) <= 64):
            raise ValueError("Device ID must be 8-64 characters")
        
        # Character whitelist
        if not re.match(r'^[a-zA-Z0-9_-]+$', value):
            raise ValueError("Device ID contains invalid characters")
        
        # SQL injection pattern detection
        sql_patterns = [
            r"(\bOR\b|\bAND\b)",
            r"(--|\#|/\*|\*/)",
            r"(\bUNION\b|\bSELECT\b|\bDROP\b|\bINSERT\b)",
            r"[';\"\\]"
        ]
        
        for pattern in sql_patterns:
            if re.search(pattern, value, re.IGNORECASE):
                raise ValueError("Device ID contains forbidden pattern")
        
        # Path traversal detection
        if "../" in value or "..\\" in value or "%2e%2e" in value.lower():
            raise ValueError("Device ID contains path traversal pattern")
        
        return value


class ChallengeRequest(StrictBaseModel):
    """Challenge generation request"""
    
    device_id: str = Field(
        ...,
        min_length=8,
        max_length=64,
        description="Device identifier"
    )
    
    trust_level: Optional[str] = Field(
        default="unknown",
        regex="^(high|medium|low|unknown)$",
        description="Trust level"
    )
    
    client_metadata: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Client metadata"
    )
    
    @validator("device_id")
    def validate_device_id(cls, v):
        return DeviceIDValidator.validate(v)
    
    @validator("client_metadata")
    def validate_metadata(cls, v):
        if v is None:
            return v
        
        # Limit metadata size
        import json
        json_str = json.dumps(v)
        if len(json_str) > 10000:  # 10KB max
            raise ValueError("Client metadata too large")
        
        # Validate nested structure
        if not isinstance(v, dict):
            raise ValueError("Client metadata must be a dictionary")
        
        # Check for dangerous keys
        dangerous_keys = ["__proto__", "constructor", "prototype"]
        for key in v.keys():
            if key.lower() in dangerous_keys:
                raise ValueError(f"Forbidden metadata key: {key}")
        
        return v


class VerifyRequest(StrictBaseModel):
    """Verification request"""
    
    device_id: str = Field(..., min_length=8, max_length=64)
    challenge_id: str = Field(..., min_length=8, max_length=128)
    token_id: str = Field(..., min_length=10, max_length=2048)
    
    # Optional fields
    audio_challenge: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Audio phrase challenge"
    )
    
    camera_attestation: Optional[str] = Field(
        default=None,
        max_length=10000,
        description="Camera attestation data (JSON)"
    )
    
    @validator("device_id", "challenge_id")
    def validate_ids(cls, v):
        return DeviceIDValidator.validate(v)
    
    @validator("token_id")
    def validate_token(cls, v):
        """Validate PASETO token format"""
        
        if not v.startswith("v4.public."):
            raise ValueError("Invalid token format")
        
        # Basic structure check
        parts = v.split(".")
        if len(parts) != 3:
            raise ValueError("Invalid token structure")
        
        return v
    
    @validator("audio_challenge")
    def validate_audio_challenge(cls, v):
        if v is None:
            return v
        
        # No special characters
        if not re.match(r'^[a-zA-Z0-9\s.,!?-]+$', v):
            raise ValueError("Audio challenge contains invalid characters")
        
        return v
    
    @validator("camera_attestation")
    def validate_attestation(cls, v):
        if v is None:
            return v
        
        # Must be valid JSON
        import json
        try:
            data = json.loads(v)
        except:
            raise ValueError("Camera attestation must be valid JSON")
        
        # Size limit
        if len(v) > 10000:
            raise ValueError("Camera attestation too large")
        
        return v


class FinalizeRequest(StrictBaseModel):
    """Finalization request"""
    
    session_id: str = Field(..., min_length=8, max_length=128)
    device_id: str = Field(..., min_length=8, max_length=64)
    
    @validator("session_id", "device_id")
    def validate_ids(cls, v):
        return DeviceIDValidator.validate(v)


class AdminRevokeRequest(StrictBaseModel):
    """Admin device revocation request"""
    
    device_id: str = Field(..., min_length=8, max_length=64)
    reason: str = Field(..., min_length=5, max_length=500)
    
    @validator("device_id")
    def validate_device_id(cls, v):
        return DeviceIDValidator.validate(v)
    
    @validator("reason")
    def validate_reason(cls, v):
        # No script tags or SQL
        forbidden = ["<script", "javascript:", "onerror=", "onclick=", "DROP", "DELETE"]
        for pattern in forbidden:
            if pattern.lower() in v.lower():
                raise ValueError("Revocation reason contains forbidden content")
        
        return v


def validate_request(request_model: type, data: Dict[str, Any]) -> BaseModel:
    """
    Validate request data against schema
    
    Args:
        request_model: Pydantic model class
        data: Request data dictionary
    
    Returns:
        Validated model instance
    
    Raises:
        ValidationError: If validation fails
    """
    
    try:
        return request_model(**data)
    except ValidationError as e:
        # Log validation errors for security monitoring
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(f"Request validation failed: {e.json()}")
        raise