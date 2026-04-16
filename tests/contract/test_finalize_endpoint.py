"""
Contract tests for /v1/finalize endpoint
"""

import pytest
import uuid


class TestFinalizeEndpoint:
    """Test /v1/finalize against OpenAPI contract"""
    
    @pytest.mark.asyncio
    async def test_finalize_response_schema(self, async_client, openapi_spec):
        """Test finalize response matches schema"""
        
        response = await async_client.post(
            "/v1/finalize",
            json={
                "device_id": f"device_{uuid.uuid4().hex[:8]}",
                "results": [
                    {
                        "challenge_passed": True,
                        "liveness_score": 0.95,
                        "confidence": 0.92
                    },
                    {
                        "challenge_passed": True,
                        "liveness_score": 0.89,
                        "confidence": 0.87
                    }
                ]
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        
        # Validate response schema
        assert "session_id" in data
        assert "trust_score" in data
        assert "trust_level" in data
        assert data["trust_level"] in ["high", "medium", "low"]
        
        # Validate breakdown
        assert "breakdown" in data
        breakdown = data["breakdown"]
        assert "liveness_factor" in breakdown
        assert "challenge_factor" in breakdown
        assert "reputation_score" in breakdown
        assert "behavior_score" in breakdown
        
        # Validate flags
        assert "flags" in data
    
    @pytest.mark.asyncio
    async def test_empty_results_validation(self, async_client):
        """Test empty results array returns validation error"""
        
        response = await async_client.post(
            "/v1/finalize",
            json={
                "device_id": f"device_{uuid.uuid4().hex[:8]}",
                "results": []
            }
        )
        
        assert response.status_code == 400
        data = response.json()
        assert "error_code" in data