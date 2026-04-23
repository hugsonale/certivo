"""
Session metadata binding for replay protection
Binds challenge tokens to capture session context
"""

import hashlib
from typing import Dict, Any, Optional
from fastapi import Request


class SessionMetadataExtractor:
    """Extract and bind session metadata to challenge tokens"""
    
    @staticmethod
    def extract_from_request(request: Request) -> Dict[str, Any]:
        """
        Extract session metadata from HTTP request
        
        Returns:
            Dictionary with hashed metadata for privacy
        """
        
        # Get client IP
        client_ip = request.client.host
        
        # Get forwarded IP if behind proxy
        x_forwarded_for = request.headers.get("X-Forwarded-For")
        if x_forwarded_for:
            client_ip = x_forwarded_for.split(",")[0].strip()
        
        # Get user agent
        user_agent = request.headers.get("User-Agent", "")
        
        # Get other browser fingerprinting data
        accept_language = request.headers.get("Accept-Language", "")
        accept_encoding = request.headers.get("Accept-Encoding", "")
        
        # Hash for privacy (don't store raw IP/UA)
        ip_hash = SessionMetadataExtractor._hash(client_ip)
        user_agent_hash = SessionMetadataExtractor._hash(user_agent)
        
        # Build metadata
        metadata = {
            "ip_hash": ip_hash,
            "user_agent_hash": user_agent_hash,
            "accept_language": accept_language[:10],  # First 10 chars only
            "accept_encoding_hash": SessionMetadataExtractor._hash(accept_encoding),
        }
        
        # Add client hints if available
        if "Sec-CH-UA-Platform" in request.headers:
            metadata["platform"] = request.headers.get("Sec-CH-UA-Platform", "")[:20]
        
        return metadata
    
    @staticmethod
    def extract_from_client_data(client_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract session metadata from client-provided data
        
        Args:
            client_data: Dictionary with client-side metadata
                - screen_resolution: "1920x1080"
                - timezone_offset: -420
                - language: "en-US"
                - platform: "MacIntel"
                - webgl_vendor: "Intel Inc."
        
        Returns:
            Processed metadata for binding
        """
        
        metadata = {}
        
        # Screen resolution
        if "screen_resolution" in client_data:
            metadata["screen_resolution"] = client_data["screen_resolution"]
        
        # Timezone offset
        if "timezone_offset" in client_data:
            metadata["timezone_offset"] = client_data["timezone_offset"]
        
        # Language
        if "language" in client_data:
            metadata["language"] = client_data["language"][:10]
        
        # Platform
        if "platform" in client_data:
            metadata["platform"] = client_data["platform"][:20]
        
        # WebGL vendor (for fingerprinting)
        if "webgl_vendor" in client_data:
            metadata["webgl_vendor_hash"] = SessionMetadataExtractor._hash(
                client_data["webgl_vendor"]
            )
        
        return metadata
    
    @staticmethod
    def merge_metadata(
        server_metadata: Dict[str, Any],
        client_metadata: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Merge server and client metadata"""
        return {**server_metadata, **client_metadata}
    
    @staticmethod
    def validate_metadata_match(
        token_metadata: Dict[str, Any],
        current_metadata: Dict[str, Any],
        strict: bool = True
    ) -> bool:
        """
        Validate that current session matches token-bound metadata
        
        Args:
            token_metadata: Metadata bound to token
            current_metadata: Current request metadata
            strict: If True, all fields must match. If False, core fields only.
        
        Returns:
            True if metadata matches, False otherwise
        """
        
        # Core fields that must always match
        core_fields = ["ip_hash", "user_agent_hash"]
        
        for field in core_fields:
            if field in token_metadata and field in current_metadata:
                if token_metadata[field] != current_metadata[field]:
                    return False
        
        # Additional fields for strict mode
        if strict:
            optional_fields = ["screen_resolution", "timezone_offset", "language"]
            
            for field in optional_fields:
                if field in token_metadata and field in current_metadata:
                    if token_metadata[field] != current_metadata[field]:
                        return False
        
        return True
    
    @staticmethod
    def _hash(value: str) -> str:
        """Hash a value with SHA256 and truncate"""
        if not value:
            return ""
        return hashlib.sha256(value.encode('utf-8')).hexdigest()[:16]