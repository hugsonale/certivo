"""
Time Authority Enforcement
Server time as sole source of truth
"""

from datetime import datetime, timedelta
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class TimeAuthority:
    """
    Server time authority
    
    Features:
    - Server time as sole source of truth
    - Client time validation (warning only)
    - Clock skew detection
    - Timestamp verification
    """
    
    # Maximum acceptable clock skew
    MAX_CLOCK_SKEW_SECONDS = 300  # 5 minutes
    
    @classmethod
    def get_current_time(cls) -> datetime:
        """
        Get current server time (UTC)
        
        This is the ONLY source of truth for time
        """
        return datetime.utcnow()
    
    @classmethod
    def is_expired(
        cls,
        expires_at: datetime,
        current_time: Optional[datetime] = None
    ) -> bool:
        """
        Check if timestamp is expired
        
        Args:
            expires_at: Expiration timestamp
            current_time: Current time (defaults to server time)
        
        Returns:
            True if expired
        """
        
        if current_time is None:
            current_time = cls.get_current_time()
        
        return current_time > expires_at
    
    @classmethod
    def validate_client_timestamp(
        cls,
        client_timestamp: datetime,
        allow_future: bool = False
    ) -> tuple[bool, Optional[str]]:
        """
        Validate client-provided timestamp
        
        Args:
            client_timestamp: Timestamp from client
            allow_future: Allow future timestamps
        
        Returns:
            (is_valid, warning_message)
        """
        
        server_time = cls.get_current_time()
        
        # Calculate clock skew
        skew = abs((client_timestamp - server_time).total_seconds())
        
        if skew > cls.MAX_CLOCK_SKEW_SECONDS:
            warning = (
                f"Clock skew detected: {skew:.0f}s "
                f"(max: {cls.MAX_CLOCK_SKEW_SECONDS}s)"
            )
            logger.warning(warning)
            return False, warning
        
        # Check if future timestamp
        if not allow_future and client_timestamp > server_time:
            warning = f"Future timestamp rejected: {client_timestamp}"
            logger.warning(warning)
            return False, warning
        
        return True, None
    
    @classmethod
    def calculate_ttl(
        cls,
        created_at: datetime,
        ttl_seconds: int
    ) -> datetime:
        """
        Calculate expiration time
        
        Args:
            created_at: Creation timestamp
            ttl_seconds: TTL in seconds
        
        Returns:
            Expiration timestamp
        """
        
        return created_at + timedelta(seconds=ttl_seconds)
    
    @classmethod
    def get_remaining_ttl(
        cls,
        expires_at: datetime,
        current_time: Optional[datetime] = None
    ) -> float:
        """
        Get remaining TTL in seconds
        
        Args:
            expires_at: Expiration timestamp
            current_time: Current time (defaults to server time)
        
        Returns:
            Remaining seconds (negative if expired)
        """
        
        if current_time is None:
            current_time = cls.get_current_time()
        
        return (expires_at - current_time).total_seconds()