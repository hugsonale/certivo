"""
Replay Attack Module
Test resistance to video replay attacks
"""

import asyncio
import httpx
import cv2
import numpy as np
from typing import Dict, Any, Tuple
import os
import tempfile
import logging

logger = logging.getLogger(__name__)


class ReplayAttackModule:
    """
    Replay attack testing
    
    Attack vector: Reuse captured legitimate verification videos
    
    Defenses tested:
    - PASETO token binding
    - Watermark validation
    - Timestamp verification
    - Challenge-response matching
    """
    
    def __init__(self):
        self.video_library = []
        self._build_video_library()
    
    def _build_video_library(self):
        """Build library of captured videos"""
        
        # In real scenario, these would be previously captured legitimate videos
        # For testing, we generate synthetic samples
        
        logger.info("📚 Building replay video library...")
        
        for i in range(10):
            video_path = f"/tmp/replay_video_{i}.mp4"
            self._generate_test_video(video_path)
            self.video_library.append(video_path)
        
        logger.info(f"   Library size: {len(self.video_library)} videos")
    
    def _generate_test_video(self, output_path: str):
        """Generate test video for replay"""
        
        # Create simple test video
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        out = cv2.VideoWriter(output_path, fourcc, 30.0, (640, 480))
        
        for i in range(90):  # 3 seconds at 30fps
            frame = np.zeros((480, 640, 3), dtype=np.uint8)
            # Add some motion
            cv2.circle(frame, (320 + i*2, 240), 50, (0, 255, 0), -1)
            out.write(frame)
        
        out.release()
    
    async def execute(
        self,
        api_base_url: str,
        config: Dict[str, Any]
    ) -> Tuple[bool, float, Dict[str, Any]]:
        """
        Execute replay attack
        
        Returns:
            (success, confidence, details)
        """
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Step 1: Get challenge
            challenge_response = await client.post(
                f"{api_base_url}/v1/challenge",
                json={
                    "device_id": "replay_test_device_001",
                    "trust_level": "unknown"
                }
            )
            
            if challenge_response.status_code != 200:
                return False, 0.0, {"error": "Challenge request failed"}
            
            challenge_data = challenge_response.json()
            token = challenge_data["token"]
            challenge_id = challenge_data["challenge_id"]
            
            # Step 2: Select random video from library
            import random
            replay_video = random.choice(self.video_library)
            
            # Step 3: Attempt to submit replayed video
            with open(replay_video, 'rb') as f:
                files = {"video": ("replay.mp4", f, "video/mp4")}
                data = {
                    "device_id": "replay_test_device_001",
                    "challenge_id": challenge_id,
                    "token_id": token
                }
                
                verify_response = await client.post(
                    f"{api_base_url}/v1/verify",
                    files=files,
                    data=data
                )
            
            # Step 4: Check if replay was successful
            if verify_response.status_code == 200:
                result = verify_response.json()
                
                if result.get("verified", False):
                    # Replay succeeded - VULNERABILITY
                    return True, 1.0, {
                        "attack": "replay_attack",
                        "video_used": replay_video,
                        "verification_result": result
                    }
                else:
                    # Replay blocked
                    return False, 0.0, {
                        "attack": "replay_attack",
                        "blocked": True,
                        "reason": result.get("reason", "Unknown")
                    }
            else:
                # Request failed
                return False, 0.0, {
                    "error": f"Verification failed: {verify_response.status_code}"
                }
    
    async def test_token_replay(
        self,
        api_base_url: str
    ) -> Tuple[bool, float, Dict[str, Any]]:
        """
        Test token replay attack
        
        Attempt to reuse PASETO tokens
        """
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Get first challenge
            response1 = await client.post(
                f"{api_base_url}/v1/challenge",
                json={"device_id": "test_device_001"}
            )
            
            token1 = response1.json()["token"]
            
            # Get second challenge
            response2 = await client.post(
                f"{api_base_url}/v1/challenge",
                json={"device_id": "test_device_001"}
            )
            
            challenge2 = response2.json()["challenge_id"]
            
            # Attempt to use token1 for challenge2 (cross-session replay)
            with open(self.video_library[0], 'rb') as f:
                files = {"video": f}
                data = {
                    "device_id": "test_device_001",
                    "challenge_id": challenge2,
                    "token_id": token1  # Wrong token for this challenge
                }
                
                verify_response = await client.post(
                    f"{api_base_url}/v1/verify",
                    files=files,
                    data=data
                )
            
            # Should be blocked
            success = verify_response.status_code == 200 and \
                     verify_response.json().get("verified", False)
            
            return success, 1.0 if success else 0.0, {
                "attack": "token_replay",
                "blocked": not success
            }