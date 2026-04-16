"""
Contract tests for /v1/verify endpoint
"""

import pytest
import httpx
import io
import uuid


class TestVerifyEndpoint:
    """Test /v1/verify against OpenAPI contract"""
    
    @pytest.mark.asyncio
    async def test_verify_response_schema(self, async_client, openapi_spec):
        """Test verify response matches schema"""
        
        # Create dummy video file
        video_content = b"fake video content for testing"
        video_file = io.BytesIO(video_content)
        
        response = await async_client.post(
            "/v1/verify",
            files={
                "video": ("test.webm", video_file, "video/webm")
            },
            data={
                "device_id": f"device_{uuid.uuid4().hex[:8]}",
                "challenge_id": f"ch_{uuid.uuid4().hex[:8]}",
                "token_id": f"tok_{uuid.uuid4().hex[:8]}"
            }
        )
        
        # Even if verification fails, response should match schema
        data = response.json()
        
        assert "challenge_passed" in data
        assert isinstance(data["challenge_passed"], bool)
        assert "liveness_score" in data
        assert isinstance(data["liveness_score"], (int, float))
        assert "confidence" in data
        
        # If error, should have error_code
        if not data["challenge_passed"]:
            assert "error_code" in data
    
    @pytest.mark.asyncio
    async def test_missing_required_fields(self, async_client):
        """Test missing required fields returns 400"""
        
        response = await async_client.post(
            "/v1/verify",
            data={"device_id": "device_123"}
            # Missing challenge_id, token_id, video
        )
        
        assert response.status_code == 400
        data = response.json()
        assert data["error_code"] == "MISSING_REQUIRED_FIELD"
    
    @pytest.mark.asyncio
    async def test_invalid_video_format(self, async_client):
        """Test invalid video format returns error code"""
        
        # Create fake txt file as video
        fake_video = io.BytesIO(b"not a video")
        
        response = await async_client.post(
            "/v1/verify",
            files={
                "video": ("test.txt", fake_video, "text/plain")
            },
            data={
                "device_id": f"device_{uuid.uuid4().hex[:8]}",
                "challenge_id": f"ch_{uuid.uuid4().hex[:8]}",
                "token_id": f"tok_{uuid.uuid4().hex[:8]}"
            }
        )
        
        assert response.status_code in [400, 422]
        data = response.json()
        assert "error_code" in data