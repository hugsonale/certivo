"""
Test idempotency behavior across all POST endpoints
"""

import pytest
import uuid


class TestIdempotency:
    """Validate idempotency key handling"""
    
    @pytest.mark.asyncio
    async def test_idempotency_header_optional(self, async_client):
        """Test requests work without idempotency key"""
        
        response = await async_client.post(
            "/v1/challenge",
            json={"device_id": f"device_{uuid.uuid4().hex[:8]}"}
        )
        
        assert response.status_code == 200
        assert "X-Idempotent-Replay" not in response.headers
    
    @pytest.mark.asyncio
    async def test_idempotency_key_caching(self, async_client):
        """Test idempotency key caches response for 24 hours"""
        
        idempotency_key = f"idem_{uuid.uuid4().hex}"
        
        # First request
        response1 = await async_client.post(
            "/v1/challenge",
            json={"device_id": f"device_{uuid.uuid4().hex[:8]}"},
            headers={"Idempotency-Key": idempotency_key}
        )
        
        assert response1.status_code == 200
        data1 = response1.json()
        
        # Subsequent requests return cached response
        for _ in range(3):
            response = await async_client.post(
                "/v1/challenge",
                json={"device_id": f"device_{uuid.uuid4().hex[:8]}"},
                headers={"Idempotency-Key": idempotency_key}
            )
            
            assert response.status_code == 200
            assert response.headers.get("X-Idempotent-Replay") == "true"
            assert response.json() == data1
    
    @pytest.mark.asyncio
    async def test_different_keys_different_responses(self, async_client):
        """Test different idempotency keys get different responses"""
        
        key1 = f"idem_{uuid.uuid4().hex}"
        key2 = f"idem_{uuid.uuid4().hex}"
        device_id = f"device_{uuid.uuid4().hex[:8]}"
        
        response1 = await async_client.post(
            "/v1/challenge",
            json={"device_id": device_id},
            headers={"Idempotency-Key": key1}
        )
        
        response2 = await async_client.post(
            "/v1/challenge",
            json={"device_id": device_id},
            headers={"Idempotency-Key": key2}
        )
        
        assert response1.status_code == 200
        assert response2.status_code == 200
        
        # Responses should be different (different challenge_ids)
        data1 = response1.json()
        data2 = response2.json()
        
        assert data1["challenges"][0]["challenge_id"] != data2["challenges"][0]["challenge_id"]