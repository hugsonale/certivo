"""
Admin Dashboard Configuration
Security settings, authentication, and access control
"""

import os
from typing import List, Optional

# ============================================================================
# ADMIN AUTHENTICATION
# ============================================================================

# Admin credentials (In production: use environment variables + hashed passwords)
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")  # Change this!

# Session configuration
SECRET_KEY = os.getenv("ADMIN_SECRET_KEY", "certivo-admin-dashboard-secret-key-change-in-production")
SESSION_COOKIE_NAME = "certivo_admin_session"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SECURE = False  # Set to True in production with HTTPS
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