"""
Centralized error code definitions
Source of truth for all API errors
"""

from enum import Enum
from typing import Dict, Any, Optional
from datetime import datetime
import uuid


class ErrorCode(str, Enum):
    """Machine-readable error codes"""
    
    # Validation errors (4xx)
    INVALID_VIDEO_FORMAT = "INVALID_VIDEO_FORMAT"
    VIDEO_TOO_LARGE = "VIDEO_TOO_LARGE"
    VIDEO_TOO_SMALL = "VIDEO_TOO_SMALL"
    MISSING_REQUIRED_FIELD = "MISSING_REQUIRED_FIELD"
    INVALID_FIELD_VALUE = "INVALID_FIELD_VALUE"
    
    # Challenge errors
    CHALLENGE_NOT_FOUND = "CHALLENGE_NOT_FOUND"
    CHALLENGE_EXPIRED = "CHALLENGE_EXPIRED"
    CHALLENGE_ALREADY_USED = "CHALLENGE_ALREADY_USED"
    INVALID_TOKEN = "INVALID_TOKEN"
    DEVICE_MISMATCH = "DEVICE_MISMATCH"
    
    # Verification errors
    ACTION_NOT_DETECTED = "ACTION_NOT_DETECTED"
    VIDEO_INTEGRITY_FAILED = "VIDEO_INTEGRITY_FAILED"
    LIVENESS_SCORE_TOO_LOW = "LIVENESS_SCORE_TOO_LOW"
    PROCESSING_ERROR = "PROCESSING_ERROR"
    
    # Security errors (403)
    DEVICE_BLOCKED = "DEVICE_BLOCKED"
    SUSPICIOUS_ACTIVITY = "SUSPICIOUS_ACTIVITY"
    BOT_DETECTED = "BOT_DETECTED"
    
    # Rate limiting (429)
    RATE_LIMIT_EXCEEDED = "RATE_LIMIT_EXCEEDED"
    
    # Authentication errors (401)
    UNAUTHORIZED = "UNAUTHORIZED"
    INVALID_CREDENTIALS = "INVALID_CREDENTIALS"
    
    # Server errors (5xx)
    INTERNAL_ERROR = "INTERNAL_ERROR"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"
    TIMEOUT = "TIMEOUT"


class APIError(Exception):
    """Base exception for API errors"""
    
    def __init__(
        self,
        error_code: ErrorCode,
        message: str,
        status_code: int = 400,
        error_details: Optional[Dict[str, Any]] = None
    ):
        self.error_code = error_code
        self.message = message
        self.status_code = status_code
        self.error_details = error_details or {}
        self.request_id = str(uuid.uuid4())
        self.timestamp = datetime.utcnow().isoformat() + "Z"
        super().__init__(message)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to API response format"""
        response = {
            "error": self.message,
            "error_code": self.error_code.value,
            "timestamp": self.timestamp,
            "request_id": self.request_id
        }
        
        if self.error_details:
            response["error_details"] = self.error_details
        
        return response


# Predefined error factories
class ValidationError(APIError):
    """400 - Bad Request"""
    def __init__(self, error_code: ErrorCode, message: str, **details):
        super().__init__(error_code, message, 400, details)


class UnauthorizedError(APIError):
    """401 - Unauthorized"""
    def __init__(self, message: str = "Invalid credentials"):
        super().__init__(ErrorCode.UNAUTHORIZED, message, 401)


class ForbiddenError(APIError):
    """403 - Forbidden"""
    def __init__(self, error_code: ErrorCode, message: str, **details):
        super().__init__(error_code, message, 403, details)


class NotFoundError(APIError):
    """404 - Not Found"""
    def __init__(self, error_code: ErrorCode, message: str):
        super().__init__(error_code, message, 404)


class RateLimitError(APIError):
    """429 - Too Many Requests"""
    def __init__(self, message: str, retry_after: int, **details):
        details['retry_after'] = retry_after
        super().__init__(ErrorCode.RATE_LIMIT_EXCEEDED, message, 429, details)


class InternalError(APIError):
    """500 - Internal Server Error"""
    def __init__(self, message: str = "Internal server error"):
        super().__init__(ErrorCode.INTERNAL_ERROR, message, 500)