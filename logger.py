"""
Certivo Logging System
Production-grade structured logging with file rotation
"""

import logging
import json
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional, Dict, Any
import os

# ============================================================================
# LOG DIRECTORY SETUP
# ============================================================================

LOGS_DIR = Path("logs")
LOGS_DIR.mkdir(exist_ok=True)

# ============================================================================
# LOG FILE PATHS
# ============================================================================

VERIFICATION_LOG = LOGS_DIR / "verification.log"
ERROR_LOG = LOGS_DIR / "errors.log"
SECURITY_LOG = LOGS_DIR / "security.log"
ADMIN_LOG = LOGS_DIR / "admin.log"
GENERAL_LOG = LOGS_DIR / "certivo.log"

# ============================================================================
# ROTATING FILE HANDLERS (10MB per file, keep 5 backups)
# ============================================================================

def create_rotating_handler(filepath: Path, level: int = logging.INFO) -> RotatingFileHandler:
    """Create a rotating file handler with JSON formatting"""
    handler = RotatingFileHandler(
        filepath,
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=5,
        encoding='utf-8'
    )
    handler.setLevel(level)
    
    # JSON formatter for structured logs
    formatter = logging.Formatter(
        '%(message)s'  # We'll format as JSON in log_event()
    )
    handler.setFormatter(formatter)
    
    return handler

# ============================================================================
# LOGGER SETUP
# ============================================================================

# General logger (all messages)
general_logger = logging.getLogger("certivo.general")
general_logger.setLevel(logging.INFO)
general_logger.addHandler(create_rotating_handler(GENERAL_LOG, logging.INFO))

# Verification logger (verification events)
verification_logger = logging.getLogger("certivo.verification")
verification_logger.setLevel(logging.INFO)
verification_logger.addHandler(create_rotating_handler(VERIFICATION_LOG, logging.INFO))

# Error logger (errors only)
error_logger = logging.getLogger("certivo.errors")
error_logger.setLevel(logging.ERROR)
error_logger.addHandler(create_rotating_handler(ERROR_LOG, logging.ERROR))

# Security logger (bot detection, rate limits)
security_logger = logging.getLogger("certivo.security")
security_logger.setLevel(logging.WARNING)
security_logger.addHandler(create_rotating_handler(SECURITY_LOG, logging.WARNING))

# Admin logger (admin actions)
admin_logger = logging.getLogger("certivo.admin")
admin_logger.setLevel(logging.INFO)
admin_logger.addHandler(create_rotating_handler(ADMIN_LOG, logging.INFO))

# Console handler (optional - also print to console)
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_formatter = logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
console_handler.setFormatter(console_formatter)

# Add console handler to general logger only
general_logger.addHandler(console_handler)

# ============================================================================
# STRUCTURED LOGGING FUNCTIONS
# ============================================================================

def log_event(
    event: str,
    session_id: str,
    challenge_id: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
    level: str = "INFO"
):
    """
    Log an event with structured JSON format
    
    Args:
        event: Event type (e.g., "verification_started", "challenge_passed")
        session_id: Session/device ID
        challenge_id: Challenge ID (optional)
        details: Additional event details (optional)
        level: Log level (INFO, WARNING, ERROR, CRITICAL)
    """
    
    payload = {
        "timestamp": datetime.utcnow().isoformat(),
        "event": event,
        "session_id": session_id,
        "challenge_id": challenge_id,
        "details": details or {},
        "level": level
    }
    
    log_message = json.dumps(payload)
    
    # Route to appropriate logger based on event type
    if event.startswith("verification_"):
        verification_logger.info(log_message)
    elif event in ["bot_detected", "rate_limit_exceeded", "suspicious_device", "device_blocked"]:
        security_logger.warning(log_message)
    elif event.startswith("admin_"):
        admin_logger.info(log_message)
    elif level == "ERROR":
        error_logger.error(log_message)
    else:
        general_logger.info(log_message)


def log_error(
    error: Exception,
    context: str,
    session_id: Optional[str] = None,
    additional_info: Optional[Dict[str, Any]] = None
):
    """
    Log an error with full context
    
    Args:
        error: The exception that occurred
        context: Where the error occurred (e.g., "video_processing")
        session_id: Session ID if available
        additional_info: Additional error context
    """
    
    payload = {
        "timestamp": datetime.utcnow().isoformat(),
        "event": "error",
        "error_type": type(error).__name__,
        "error_message": str(error),
        "context": context,
        "session_id": session_id,
        "additional_info": additional_info or {},
        "level": "ERROR"
    }
    
    error_logger.error(json.dumps(payload))
    
    # Also send to Sentry if configured
    try:
        import sentry_sdk
        sentry_sdk.capture_exception(error)
    except:
        pass


def log_security_event(
    event_type: str,
    device_id: str,
    ip_address: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None
):
    """
    Log a security-related event
    
    Args:
        event_type: Type of security event
        device_id: Device ID involved
        ip_address: IP address if available
        details: Additional security details
    """
    
    payload = {
        "timestamp": datetime.utcnow().isoformat(),
        "event": "security_event",
        "event_type": event_type,
        "device_id": device_id,
        "ip_address": ip_address,
        "details": details or {},
        "level": "WARNING"
    }
    
    security_logger.warning(json.dumps(payload))


def log_admin_action(
    admin_user: str,
    action: str,
    target: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None
):
    """
    Log an admin action
    
    Args:
        admin_user: Admin username
        action: Action performed (e.g., "revoke_trust", "view_logs")
        target: Target of action (e.g., device_id)
        details: Additional action details
    """
    
    payload = {
        "timestamp": datetime.utcnow().isoformat(),
        "event": "admin_action",
        "admin_user": admin_user,
        "action": action,
        "target": target,
        "details": details or {},
        "level": "INFO"
    }
    
    admin_logger.info(json.dumps(payload))


def log_performance(
    operation: str,
    duration_ms: float,
    session_id: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None
):
    """
    Log performance metrics
    
    Args:
        operation: Operation name (e.g., "video_processing")
        duration_ms: Duration in milliseconds
        session_id: Session ID if available
        details: Additional performance details
    """
    
    payload = {
        "timestamp": datetime.utcnow().isoformat(),
        "event": "performance_metric",
        "operation": operation,
        "duration_ms": duration_ms,
        "session_id": session_id,
        "details": details or {},
        "level": "INFO"
    }
    
    verification_logger.info(json.dumps(payload))


# ============================================================================
# STARTUP MESSAGE
# ============================================================================

print("=" * 70)
print("📊 CERTIVO LOGGING SYSTEM INITIALIZED")
print("=" * 70)
print(f"✅ General logs: {GENERAL_LOG}")
print(f"✅ Verification logs: {VERIFICATION_LOG}")
print(f"✅ Error logs: {ERROR_LOG}")
print(f"✅ Security logs: {SECURITY_LOG}")
print(f"✅ Admin logs: {ADMIN_LOG}")
print(f"📦 Rotation: 10MB per file, 5 backups (50MB total per log type)")
print("=" * 70)