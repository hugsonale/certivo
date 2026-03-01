"""
Admin Authentication System
Handles login, logout, session management, and access control
"""

from fastapi import Request, HTTPException, status
from fastapi.responses import RedirectResponse
from datetime import datetime, timedelta
from typing import Optional, Dict
import hashlib
import secrets
from admin import config
import bcrypt

# ============================================================================
# SESSION STORAGE (In-memory for simplicity - use Redis in production)
# ============================================================================

active_sessions: Dict[str, Dict] = {}
login_attempts: Dict[str, Dict] = {}  # Track failed login attempts


# ============================================================================
# PASSWORD HASHING
# ============================================================================



def hash_password(password: str) -> str:
    """Hash password using bcrypt"""
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
    return hashed.decode('utf-8')


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify password against bcrypt hash"""
    try:
        return bcrypt.checkpw(
            plain_password.encode('utf-8'),
            hashed_password.encode('utf-8')
        )
    except Exception as e:
        print(f"❌ Password verification error: {e}")
        return False


# ============================================================================
# LOGIN ATTEMPT TRACKING
# ============================================================================

def is_ip_locked(ip: str) -> bool:
    """Check if IP is temporarily locked due to failed attempts"""
    if ip not in login_attempts:
        return False
    
    attempt_data = login_attempts[ip]
    locked_until = attempt_data.get('locked_until')
    
    if locked_until and datetime.utcnow() < locked_until:
        return True
    
    # Unlock if lockout period expired
    if locked_until and datetime.utcnow() >= locked_until:
        login_attempts[ip] = {'count': 0, 'locked_until': None}
        return False
    
    return False


def record_failed_login(ip: str):
    """Record a failed login attempt"""
    if ip not in login_attempts:
        login_attempts[ip] = {'count': 0, 'locked_until': None}
    
    login_attempts[ip]['count'] += 1
    
    # Lock IP if max attempts exceeded
    if login_attempts[ip]['count'] >= config.LOGIN_MAX_ATTEMPTS:
        login_attempts[ip]['locked_until'] = datetime.utcnow() + timedelta(
            seconds=config.LOGIN_LOCKOUT_DURATION
        )
        print(f"🔒 IP {ip} locked for {config.LOGIN_LOCKOUT_DURATION}s due to failed login attempts")


def reset_login_attempts(ip: str):
    """Reset login attempts for IP (called on successful login)"""
    if ip in login_attempts:
        login_attempts[ip] = {'count': 0, 'locked_until': None}


# ============================================================================
# SESSION MANAGEMENT
# ============================================================================

def create_session(username: str, ip: str) -> str:
    """Create a new admin session and return session token"""
    session_token = secrets.token_urlsafe(32)
    
    active_sessions[session_token] = {
        'username': username,
        'ip': ip,
        'created_at': datetime.utcnow(),
        'last_activity': datetime.utcnow()
    }
    
    print(f"✅ Admin session created for {username} from {ip}")
    return session_token


def validate_session(session_token: str, ip: str) -> bool:
    """Validate that a session token is valid and not expired"""
    if not session_token or session_token not in active_sessions:
        return False
    
    session = active_sessions[session_token]
    
    # Check if session expired
    created_at = session['created_at']
    if datetime.utcnow() > created_at + timedelta(seconds=config.SESSION_MAX_AGE):
        destroy_session(session_token)
        return False
    
    # Update last activity
    session['last_activity'] = datetime.utcnow()
    
    return True


def get_session(session_token: str) -> Optional[Dict]:
    """Get session data"""
    return active_sessions.get(session_token)


def destroy_session(session_token: str):
    """Destroy an admin session"""
    if session_token in active_sessions:
        username = active_sessions[session_token].get('username', 'unknown')
        del active_sessions[session_token]
        print(f"🚪 Admin session destroyed for {username}")


# ============================================================================
# AUTHENTICATION
# ============================================================================

def authenticate(username: str, password: str, ip: str) -> Optional[str]:
    """
    Authenticate admin user with bcrypt password hashing
    Returns session token if successful, None otherwise
    """
    
    # Check if IP is locked
    if is_ip_locked(ip):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many failed login attempts. Try again in {config.LOGIN_LOCKOUT_DURATION // 60} minutes."
        )
    
    # Validate username
    if username != config.ADMIN_USERNAME:
        record_failed_login(ip)
        return None
    
    # ✅ NEW: Hash the stored password on first use (for migration)
    # This allows smooth transition from plain text to bcrypt
    stored_password = config.ADMIN_PASSWORD
    
    # Check if stored password is already hashed (bcrypt hashes start with $2b$)
    if not stored_password.startswith('$2b$'):
        # Plain text password - verify directly and hash for next time
        if password == stored_password:
            reset_login_attempts(ip)
            return create_session(username, ip)
        else:
            record_failed_login(ip)
            return None
    else:
        # Hashed password - use bcrypt verification
        if verify_password(password, stored_password):
            reset_login_attempts(ip)
            return create_session(username, ip)
        else:
            record_failed_login(ip)
            return None


# ============================================================================
# ACCESS CONTROL
# ============================================================================

def check_ip_whitelist(ip: str) -> bool:
    """Check if IP is in whitelist (if IP restriction enabled)"""
    if not config.IP_RESTRICTION_ENABLED:
        return True
    
    if not config.ALLOWED_IPS:
        return True
    
    return ip in config.ALLOWED_IPS


def require_auth(request: Request) -> Dict:
    """
    Dependency to require authentication for admin routes
    Raises HTTPException if not authenticated
    Returns session data if authenticated
    """
    
    # Get client IP
    client_ip = request.client.host if request.client else "unknown"
    
    # Check IP whitelist
    if not check_ip_whitelist(client_ip):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: IP not authorized"
        )
    
    # Get session token from cookie
    session_token = request.cookies.get(config.SESSION_COOKIE_NAME)
    
    if not session_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated"
        )
    
    # Validate session
    if not validate_session(session_token, client_ip):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired or invalid"
        )
    
    return get_session(session_token)


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def get_client_ip(request: Request) -> str:
    """Extract client IP from request"""
    # Check X-Forwarded-For header (if behind proxy)
    forwarded = request.headers.get('X-Forwarded-For')
    if forwarded:
        return forwarded.split(',')[0].strip()
    
    # Check X-Real-IP header
    real_ip = request.headers.get('X-Real-IP')
    if real_ip:
        return real_ip
    
    # Fallback to direct client IP
    return request.client.host if request.client else "unknown"


def create_redirect_to_login() -> RedirectResponse:
    """Create redirect response to login page"""
    return RedirectResponse(url="/admin/login", status_code=status.HTTP_303_SEE_OTHER)


# ============================================================================
# SESSION CLEANUP (Call periodically)
# ============================================================================

def cleanup_expired_sessions():
    """Remove expired sessions (run periodically in production)"""
    now = datetime.utcnow()
    expired = []
    
    for token, session in active_sessions.items():
        created_at = session['created_at']
        if now > created_at + timedelta(seconds=config.SESSION_MAX_AGE):
            expired.append(token)
    
    for token in expired:
        destroy_session(token)
    
    if expired:
        print(f"🧹 Cleaned up {len(expired)} expired admin sessions")