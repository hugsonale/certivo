"""
Contract tests for /v1/challenge endpoint
"""

import pytest
import httpx
from jsonschema import validate
import uuid


class TestChallengeEndpoint:
    """Test /v1/challenge against OpenAPI contract"""
    
    @pytest.mark.asyncio
    async def test_valid_challenge_request(self, async_client, openapi_spec):
        """Test valid challenge request returns correct schema"""
        
        # Get schema from OpenAPI spec
        challenge_schema = openapi_spec["components"]["schemas"]["ChallengeResponse"]
        
        # Make request
        response = await async_client.post(
            "/v1/challenge",
            json={"device_id": f"device_test_{uuid.uuid4().hex[:8]}"}
        )
        
        # Assert status code
        assert response.status_code == 200
        
        # Validate response against schema
        data = response.json()
        assert "challenges" in data
        assert isinstance(data["challenges"], list)
        assert len(data["challenges"]) > 0
        
        # Validate challenge structure
        for challenge in data["challenges"]:
            assert "challenge_id" in challenge
            assert "token_id" in challenge
            assert "instruction" in challenge
            assert "difficulty" in challenge
            assert "expires_at" in challenge
            assert challenge["difficulty"] in ["easy", "medium", "hard"]
    
    @pytest.mark.asyncio
    async def test_missing_device_id(self, async_client):
        """Test missing device_id returns 400 with error code"""
        
        response = await async_client.post(
            "/v1/challenge",
            json={}
        )
        
        assert response.status_code == 400
        data = response.json()
        
        # Validate error schema
        assert "error" in data
        assert "error_code" in data
        assert data["error_code"] == "MISSING_REQUIRED_FIELD"
        assert "timestamp" in data
    
    @pytest.mark.asyncio
    async def test_idempotency_key_support(self, async_client):
        """Test idempotency key returns same response"""
        
        idempotency_key = f"idem_{uuid.uuid4().hex}"
        device_id = f"device_{uuid.uuid4().hex[:8]}"
        
        # First request
        response1 = await async_client.post(
            "/v1/challenge",
            json={"device_id": device_id},
            headers={"Idempotency-Key": idempotency_key}
        )
        
        assert response1.status_code == 200
        data1 = response1.json()
        
        # Second request with same key
        response2 = await async_client.post(
            "/v1/challenge",
            json={"device_id": device_id},
            headers={"Idempotency-Key": idempotency_key}
        )
        
        assert response2.status_code == 200
        data2 = response2.json()
        
        # Should return identical response
        assert data1 == data2
        assert response2.headers.get("X-Idempotent-Replay") == "true"
    
    @pytest.mark.asyncio
    async def test_rate_limiting(self, async_client):
        """Test rate limiting returns 429"""
        
        # Make requests until rate limited (limit is 10/minute)
        device_id = f"device_{uuid.uuid4().hex[:8]}"
        
        for i in range(15):
            response = await async_client.post(
                "/v1/challenge",
                json={"device_id": f"{device_id}_{i}"}
            )
            
            if response.status_code == 429:
                data = response.json()
                assert data["error_code"] == "RATE_LIMIT_EXCEEDED"
                assert "retry_after" in data.get("error_details", {})
                return
        
        pytest.fail("Rate limiting not triggered after 15 requests")