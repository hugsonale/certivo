"""
Test error code consistency across all endpoints
"""

import pytest


class TestErrorCodes:
    """Validate error codes match OpenAPI specification"""
    
    def test_all_error_codes_documented(self, openapi_spec):
        """Ensure all error codes are documented in OpenAPI"""
        
        # Extract all error codes from OpenAPI spec
        verify_response = openapi_spec["components"]["schemas"]["VerifyResponse"]
        error_code_enum = verify_response["properties"]["error_code"]["enum"]
        
        # Expected error codes
        expected_codes = [
            "ACTION_NOT_DETECTED",
            "VIDEO_INTEGRITY_FAILED",
            "CHALLENGE_EXPIRED",
            "INVALID_TOKEN",
            "DEVICE_BLOCKED",
            "RATE_LIMIT_EXCEEDED",
            "PROCESSING_ERROR"
        ]
        
        for code in expected_codes:
            assert code in error_code_enum, f"Error code {code} not documented"
    
    @pytest.mark.asyncio
    async def test_error_response_format(self, async_client):
        """Test all errors follow consistent format"""
        
        # Trigger a validation error
        response = await async_client.post(
            "/v1/challenge",
            json={}
        )
        
        assert response.status_code == 400
        data = response.json()
        
        # Validate error format
        required_fields = ["error", "error_code", "timestamp"]
        for field in required_fields:
            assert field in data, f"Missing required error field: {field}"
        
        # Validate timestamp format (ISO 8601)
        import re
        iso8601_pattern = r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$'
        assert re.match(iso8601_pattern, data["timestamp"])