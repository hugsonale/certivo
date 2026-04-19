"""
ASN (Autonomous System Number) lookup for network-level rate limiting
"""

import httpx
import ipaddress
from typing import Optional, Dict
import asyncio


class ASNLookupService:
    """
    Lookup ASN for IP addresses
    Uses ipinfo.io API (or similar)
    """
    
    def __init__(self, api_token: Optional[str] = None):
        self.api_token = api_token
        self.cache: Dict[str, str] = {}
        self.cache_ttl = 3600  # 1 hour
    
    async def get_asn(self, ip: str) -> Optional[str]:
        """
        Get ASN for IP address
        Returns: ASN string like "AS15169" or None
        """
        # Check cache
        if ip in self.cache:
            return self.cache[ip]
        
        # Validate IP
        try:
            ipaddress.ip_address(ip)
        except ValueError:
            return None
        
        # Skip private/local IPs
        ip_obj = ipaddress.ip_address(ip)
        if ip_obj.is_private or ip_obj.is_loopback:
            return None
        
        try:
            # Use ipinfo.io API (free tier available)
            url = f"https://ipinfo.io/{ip}/json"
            headers = {}
            
            if self.api_token:
                headers["Authorization"] = f"Bearer {self.api_token}"
            
            async with httpx.AsyncClient() as client:
                response = await client.get(url, headers=headers, timeout=2.0)
                
                if response.status_code == 200:
                    data = response.json()
                    asn = data.get("org", "").split()[0]  # Format: "AS15169 Google LLC"
                    
                    if asn.startswith("AS"):
                        self.cache[ip] = asn
                        return asn
        
        except Exception:
            pass
        
        return None


# Global ASN lookup instance
asn_lookup = ASNLookupService()