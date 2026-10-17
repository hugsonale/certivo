"""
WAF integration helpers
Extract and validate WAF headers
"""

from typing import Optional, Dict, Any
from fastapi import Request


class WAFHeaders:
    """Extract WAF-provided security headers"""
    
    @staticmethod
    def extract_cloudflare_headers(request: Request) -> Dict[str, Any]:
        """Extract Cloudflare security headers"""
        return {
            "cf_ray": request.headers.get("CF-Ray"),
            "cf_connecting_ip": request.headers.get("CF-Connecting-IP"),
            "cf_ipcountry": request.headers.get("CF-IPCountry"),
            "cf_threat_score": request.headers.get("CF-Threat-Score"),
            "cf_bot_score": request.headers.get("CF-Bot-Management-Score"),
            "cf_verified_bot": request.headers.get("CF-Verified-Bot")
        }
    
    @staticmethod
    def extract_aws_waf_headers(request: Request) -> Dict[str, Any]:
        """Extract AWS WAF headers"""
        return {
            "x_amzn_waf_action": request.headers.get("X-Amzn-Waf-Action"),
            "x_amzn_trace_id": request.headers.get("X-Amzn-Trace-Id"),
            "x_forwarded_for": request.headers.get("X-Forwarded-For")
        }
    
    @staticmethod
    def get_real_ip(request: Request) -> str:
        """Get real client IP (considering proxies/WAF)"""
        # Cloudflare
        if request.headers.get("CF-Connecting-IP"):
            return request.headers.get("CF-Connecting-IP")
        
        # AWS ALB/CloudFront
        if request.headers.get("X-Forwarded-For"):
            return request.headers.get("X-Forwarded-For").split(",")[0].strip()
        
        # Direct connection
        return request.client.host
    
    @staticmethod
    def is_verified_bot(request: Request) -> bool:
        """Check if request is from verified bot (Cloudflare)"""
        return request.headers.get("CF-Verified-Bot") == "true"
    
    @staticmethod
    def get_threat_score(request: Request) -> int:
        """Get Cloudflare threat score (0-100)"""
        score = request.headers.get("CF-Threat-Score")
        if score:
            try:
                return int(score)
            except ValueError:
                pass
        return 0