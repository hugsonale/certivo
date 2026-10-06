"""
Multi-Factor Authentication (MFA) Implementation
TOTP-based 2FA for admin access
"""

import pyotp
import qrcode
import io
import base64
from typing import Dict, Any, Optional, Tuple
from datetime import datetime, timedelta
import secrets
import hashlib


class MFAManager:
    """
    Manage TOTP-based Multi-Factor Authentication
    
    Features:
    - TOTP token generation and validation
    - QR code generation for authenticator apps
    - Backup codes generation
    - Rate limiting on verification attempts
    """
    
    def __init__(self, issuer_name: str = "Certivo"):
        self.issuer_name = issuer_name
        self.totp_window = 1  # Accept tokens from +/- 1 time window (30 seconds)
        self.max_attempts = 5  # Max failed attempts before lockout
        self.lockout_duration = 900  # 15 minutes
    
    def generate_secret(self) -> str:
        """
        Generate cryptographically secure TOTP secret
        
        Returns:
            Base32 encoded secret (32 characters)
        """
        return pyotp.random_base32()
    
    def generate_qr_code(
        self,
        username: str,
        secret: str
    ) -> str:
        """
        Generate QR code for authenticator app enrollment
        
        Args:
            username: Admin username
            secret: TOTP secret
        
        Returns:
            Base64 encoded PNG image
        """
        
        # Create provisioning URI
        totp = pyotp.TOTP(secret)
        provisioning_uri = totp.provisioning_uri(
            name=username,
            issuer_name=self.issuer_name
        )
        
        # Generate QR code
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(provisioning_uri)
        qr.make(fit=True)
        
        img = qr.make_image(fill_color="black", back_color="white")
        
        # Convert to base64
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        buffer.seek(0)
        
        img_base64 = base64.b64encode(buffer.read()).decode()
        
        return f"data:image/png;base64,{img_base64}"
    
    def generate_backup_codes(self, count: int = 10) -> list[str]:
        """
        Generate one-time backup codes
        
        Args:
            count: Number of backup codes to generate
        
        Returns:
            List of backup codes (8 characters each)
        """
        
        codes = []
        for _ in range(count):
            # Generate cryptographically secure random code
            code = secrets.token_hex(4).upper()  # 8 characters
            codes.append(code)
        
        return codes
    
    def hash_backup_code(self, code: str) -> str:
        """Hash backup code for storage"""
        return hashlib.sha256(code.encode()).hexdigest()
    
    def verify_totp(
        self,
        secret: str,
        token: str
    ) -> bool:
        """
        Verify TOTP token
        
        Args:
            secret: User's TOTP secret
            token: 6-digit token from authenticator app
        
        Returns:
            True if valid, False otherwise
        """
        
        if not token or len(token) != 6 or not token.isdigit():
            return False
        
        totp = pyotp.TOTP(secret)
        
        # Verify with time window (allows for clock drift)
        return totp.verify(token, valid_window=self.totp_window)
    
    def verify_backup_code(
        self,
        stored_hash: str,
        provided_code: str
    ) -> bool:
        """
        Verify backup code
        
        Args:
            stored_hash: SHA256 hash of backup code
            provided_code: Code provided by user
        
        Returns:
            True if matches, False otherwise
        """
        
        provided_hash = self.hash_backup_code(provided_code.upper())
        
        # Constant-time comparison to prevent timing attacks
        return secrets.compare_digest(stored_hash, provided_hash)


class MFAEnrollment:
    """Track MFA enrollment status"""
    
    def __init__(self, redis_client):
        self.redis = redis_client
    
    async def start_enrollment(
        self,
        user_id: str,
        secret: str,
        backup_codes_hashed: list[str]
    ) -> str:
        """
        Start MFA enrollment process
        
        Returns:
            Enrollment ID
        """
        
        enrollment_id = secrets.token_urlsafe(32)
        
        enrollment_data = {
            "user_id": user_id,
            "secret": secret,
            "backup_codes": ",".join(backup_codes_hashed),
            "status": "pending",
            "created_at": datetime.utcnow().isoformat()
        }
        
        # Store with 15 minute expiry
        await self.redis.hset(
            f"mfa_enrollment:{enrollment_id}",
            mapping=enrollment_data
        )
        await self.redis.expire(f"mfa_enrollment:{enrollment_id}", 900)
        
        return enrollment_id
    
    async def complete_enrollment(
        self,
        enrollment_id: str,
        verification_token: str
    ) -> Optional[Dict[str, Any]]:
        """
        Complete MFA enrollment after verifying first token
        
        Returns:
            Enrollment data if successful, None otherwise
        """
        
        enrollment_data = await self.redis.hgetall(f"mfa_enrollment:{enrollment_id}")
        
        if not enrollment_data:
            return None
        
        # Verify token
        mfa = MFAManager()
        secret = enrollment_data["secret"]
        
        if not mfa.verify_totp(secret, verification_token):
            return None
        
        # Mark as completed
        await self.redis.hset(
            f"mfa_enrollment:{enrollment_id}",
            "status",
            "completed"
        )
        
        return enrollment_data
    
    async def get_enrollment(self, enrollment_id: str) -> Optional[Dict[str, Any]]:
        """Get enrollment data"""
        
        data = await self.redis.hgetall(f"mfa_enrollment:{enrollment_id}")
        return dict(data) if data else None


class MFARateLimiter:
    """Rate limit MFA verification attempts"""
    
    def __init__(self, redis_client):
        self.redis = redis_client
        self.max_attempts = 5
        self.lockout_duration = 900  # 15 minutes
    
    async def record_attempt(
        self,
        user_id: str,
        success: bool
    ) -> Tuple[bool, int, Optional[int]]:
        """
        Record MFA verification attempt
        
        Returns:
            (is_locked_out, attempts_remaining, lockout_seconds)
        """
        
        key = f"mfa_attempts:{user_id}"
        
        # Check if locked out
        lockout_key = f"mfa_lockout:{user_id}"
        is_locked = await self.redis.exists(lockout_key)
        
        if is_locked:
            ttl = await self.redis.ttl(lockout_key)
            return True, 0, ttl
        
        # Increment attempt counter
        attempts = await self.redis.incr(key)
        
        if attempts == 1:
            # First attempt - set expiry
            await self.redis.expire(key, 300)  # 5 minutes
        
        if success:
            # Reset on success
            await self.redis.delete(key)
            return False, self.max_attempts, None
        
        # Check if should lock out
        if attempts >= self.max_attempts:
            # Lock out for 15 minutes
            await self.redis.setex(lockout_key, self.lockout_duration, "1")
            await self.redis.delete(key)
            return True, 0, self.lockout_duration
        
        attempts_remaining = self.max_attempts - attempts
        return False, attempts_remaining, None