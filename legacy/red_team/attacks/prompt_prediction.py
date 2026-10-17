"""
Prompt Prediction Attack Module
Test resistance to challenge prediction and farming
"""

import asyncio
import httpx
from typing import Dict, Any, Tuple, List
from collections import Counter
import logging

logger = logging.getLogger(__name__)


class PromptPredictionModule:
    """
    Prompt prediction attack testing
    
    Attack vectors:
    - Challenge entropy analysis
    - Pattern recognition
    - Pre-computed solutions
    - Challenge farming
    
    Defenses tested:
    - Challenge entropy (>= 20 bits)
    - Template rotation
    - CSPRNG usage
    - Time-limited challenges
    """
    
    def __init__(self):
        self.observed_challenges = []
        self.solution_library = {}
    
    async def execute(
        self,
        api_base_url: str,
        config: Dict[str, Any]
    ) -> Tuple[bool, float, Dict[str, Any]]:
        """Execute prompt prediction attack"""
        
        attack_type = config.get("type", "entropy_analysis")
        
        if attack_type == "entropy_analysis":
            return await self._test_entropy_analysis(api_base_url)
        elif attack_type == "pattern_recognition":
            return await self._test_pattern_recognition(api_base_url)
        elif attack_type == "challenge_farming":
            return await self._test_challenge_farming(api_base_url)
        else:
            return False, 0.0, {"error": "Unknown attack type"}
    
    async def _test_entropy_analysis(
        self,
        api_base_url: str
    ) -> Tuple[bool, float, Dict[str, Any]]:
        """
        Test challenge entropy
        
        Collect multiple challenges and analyze entropy
        """
        
        challenges = []
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Collect 100 challenges
            for i in range(100):
                response = await client.post(
                    f"{api_base_url}/v1/challenge",
                    json={"device_id": f"entropy_test_{i}"}
                )
                
                if response.status_code == 200:
                    challenge_data = response.json()
                    challenges.append(challenge_data.get("actions", []))
                
                await asyncio.sleep(0.1)
        
        # Analyze entropy
        entropy = self._calculate_challenge_entropy(challenges)
        
        # Low entropy means predictable challenges
        low_entropy = entropy < 20.0  # bits
        
        return low_entropy, 1.0 if low_entropy else 0.0, {
            "attack": "entropy_analysis",
            "entropy_bits": entropy,
            "threshold": 20.0,
            "vulnerable": low_entropy,
            "challenges_analyzed": len(challenges)
        }
    
    async def _test_pattern_recognition(
        self,
        api_base_url: str
    ) -> Tuple[bool, float, Dict[str, Any]]:
        """
        Test pattern recognition in challenges
        
        Look for repeating patterns or sequences
        """
        
        challenges = []
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            for i in range(50):
                response = await client.post(
                    f"{api_base_url}/v1/challenge",
                    json={"device_id": f"pattern_test_{i}"}
                )
                
                if response.status_code == 200:
                    challenge_data = response.json()
                    
                    # Extract challenge structure
                    actions = challenge_data.get("actions", [])
                    challenge_tuple = tuple(
                        (a.get("action"), a.get("direction"))
                        for a in actions
                    )
                    
                    challenges.append(challenge_tuple)
        
        # Look for duplicates
        challenge_counts = Counter(challenges)
        duplicates = sum(1 for count in challenge_counts.values() if count > 1)
        duplicate_rate = duplicates / len(challenges)
        
        # Pattern detected if many duplicates
        pattern_detected = duplicate_rate > 0.10  # 10% duplicates
        
        return pattern_detected, 1.0 if pattern_detected else 0.0, {
            "attack": "pattern_recognition",
            "duplicate_rate": duplicate_rate,
            "total_challenges": len(challenges),
            "unique_challenges": len(challenge_counts),
            "vulnerable": pattern_detected
        }
    
    async def _test_challenge_farming(
        self,
        api_base_url: str
    ) -> Tuple[bool, float, Dict[str, Any]]:
        """
        Test challenge farming attack
        
        Pre-compute solutions for common challenges
        """
        
        # Build solution library
        await self._farm_challenges(api_base_url, num_challenges=100)
        
        # Test prediction accuracy
        correct_predictions = 0
        total_attempts = 20
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            for i in range(total_attempts):
                # Get new challenge
                response = await client.post(
                    f"{api_base_url}/v1/challenge",
                    json={"device_id": f"farm_test_{i}"}
                )
                
                challenge_data = response.json()
                actions = tuple(
                    (a.get("action"), a.get("direction"))
                    for a in challenge_data.get("actions", [])
                )
                
                # Check if we have pre-computed solution
                if actions in self.solution_library:
                    correct_predictions += 1
        
        prediction_rate = correct_predictions / total_attempts
        
        # High prediction rate = vulnerable
        vulnerable = prediction_rate > 0.20  # 20% prediction success
        
        return vulnerable, prediction_rate, {
            "attack": "challenge_farming",
            "prediction_rate": prediction_rate,
            "library_size": len(self.solution_library),
            "vulnerable": vulnerable
        }
    
    async def _farm_challenges(
        self,
        api_base_url: str,
        num_challenges: int
    ):
        """Farm challenges to build solution library"""
        
        logger.info(f"🌾 Farming {num_challenges} challenges...")
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            for i in range(num_challenges):
                response = await client.post(
                    f"{api_base_url}/v1/challenge",
                    json={"device_id": f"farm_device_{i}"}
                )
                
                if response.status_code == 200:
                    challenge_data = response.json()
                    actions = tuple(
                        (a.get("action"), a.get("direction"))
                        for a in challenge_data.get("actions", [])
                    )
                    
                    # Store in library (in real attack, would store solution)
                    self.solution_library[actions] = {
                        "challenge_id": challenge_data["challenge_id"],
                        "token": challenge_data["token"]
                    }
                
                await asyncio.sleep(0.1)
        
        logger.info(f"   Library size: {len(self.solution_library)}")
    
    def _calculate_challenge_entropy(
        self,
        challenges: List[List[Dict]]
    ) -> float:
        """
        Calculate entropy of challenge set
        
        H = log2(N) where N = number of unique combinations
        """
        
        import math
        
        # Convert challenges to tuples for counting
        challenge_tuples = []
        for challenge in challenges:
            challenge_tuple = tuple(
                (a.get("action"), a.get("direction"))
                for a in challenge
            )
            challenge_tuples.append(challenge_tuple)
        
        # Count unique challenges
        unique_challenges = len(set(challenge_tuples))
        
        # Calculate entropy
        if unique_challenges > 1:
            entropy = math.log2(unique_challenges)
        else:
            entropy = 0.0
        
        return entropy