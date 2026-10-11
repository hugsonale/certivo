"""
Admin Dashboard Configuration
Security settings, authentication, and access control
"""

import os
from typing import List, Optional
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# ============================================================================
# ADMIN AUTHENTICATION
# ============================================================================

# Admin credentials from environment variables
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")  # No default - must be in .env!

# Validate that password is set
if not ADMIN_PASSWORD:
    raise ValueError(
        "❌ ADMIN_PASSWORD not set! Please create a .env file with ADMIN_PASSWORD=your_password"
    )

# Session configuration
SECRET_KEY = os.getenv("ADMIN_SECRET_KEY")
if not SECRET_KEY:
    raise ValueError(
        "❌ ADMIN_SECRET_KEY not set! Generate one with: python -c \"import secrets; print(secrets.token_urlsafe(48))\""
    )

SESSION_COOKIE_NAME = "certivo_admin_session"
SESSION_COOKIE_HTTPONLY = True

# HTTPS enforcement - set to True in production
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
SESSION_COOKIE_SECURE = (ENVIRONMENT == "production")  # True only in production

SESSION_MAX_AGE = 3600 * 8  # 8 hours

# ============================================================================
# ACCESS CONTROL
# ============================================================================

# IP whitelist (Optional - leave empty to allow all IPs)
ALLOWED_IPS: List[str] = [
    # "127.0.0.1",
    # "192.168.1.100",
]

# Enable IP restriction
IP_RESTRICTION_ENABLED = False

# Rate limiting
LOGIN_MAX_ATTEMPTS = 5
LOGIN_LOCKOUT_DURATION = 300  # 5 minutes in seconds

# ============================================================================
# DASHBOARD SETTINGS
# ============================================================================

# Pagination
ITEMS_PER_PAGE = 50

# Date range for metrics (days)
METRICS_DEFAULT_DAYS = 7

# Alert thresholds
ALERT_HIGH_FAILURE_RATE = 30  # % of failures triggers alert
ALERT_SUSPICIOUS_ATTEMPTS_PER_IP = 10  # attempts from same IP
ALERT_NO_FACE_DETECTION_RATE = 20  # % of no-face errors

# System health thresholds
CPU_WARNING_THRESHOLD = 80  # %
MEMORY_WARNING_THRESHOLD = 80  # %
PROCESSING_TIME_WARNING = 3000  # milliseconds

# ============================================================================
# LOGGING
# ============================================================================

ADMIN_LOG_FILE = "logs/admin_access.log"
ADMIN_LOG_LEVEL = "INFO"

# ============================================================================
# FEATURES
# ============================================================================

# Enable/disable dashboard features
ENABLE_DEVICE_REVOCATION = True
ENABLE_CHALLENGE_DELETION = True
ENABLE_SESSION_INSPECTION = True
ENABLE_SYSTEM_HEALTH = True

# ============================================================================
# SECURITY
# ============================================================================

# Max upload size (bytes)
MAX_UPLOAD_SIZE = int(os.getenv("MAX_UPLOAD_SIZE", 10485760))  # 10MB default

# Rate limiting
RATE_LIMIT_ENABLED = os.getenv("RATE_LIMIT_ENABLED", "true").lower() == "true"

print("✅ Admin config loaded from environment variables")
print(f"   Environment: {ENVIRONMENT}")
print(f"   HTTPS Cookies: {SESSION_COOKIE_SECURE}")
print(f"   Rate Limiting: {RATE_LIMIT_ENABLED}")