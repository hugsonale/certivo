"""
Cryptographic challenge generation with high entropy
Ensures unpredictability and prevents prerecorded attacks
"""

import secrets
import hashlib
import json
from typing import List, Dict, Any, Tuple, Optional
from enum import Enum
from datetime import datetime
import math


class ChallengeType(str, Enum):
    """Base challenge types"""
    HEAD_TURN = "head_turn"
    BLINK = "blink"
    NOD = "nod"
    MOUTH = "mouth"
    EYEBROW = "eyebrow"
    SMILE = "smile"
    FROWN = "frown"
    TONGUE = "tongue"
    WINK = "wink"


class Direction(str, Enum):
    """Directional movements"""
    LEFT = "left"
    RIGHT = "right"
    UP = "up"
    DOWN = "down"


class Intensity(str, Enum):
    """Movement intensity levels"""
    SUBTLE = "subtle"
    NORMAL = "normal"
    EXAGGERATED = "exaggerated"


class Timing(str, Enum):
    """Timing variations"""
    FAST = "fast"      # < 1 second
    NORMAL = "normal"  # 1-2 seconds
    SLOW = "slow"      # 2-3 seconds


class ChallengeTemplate:
    """Multi-step challenge template with entropy calculation"""
    
    def __init__(
        self,
        template_id: str,
        steps: List[Dict[str, Any]],
        min_entropy_bits: float,
        description: str
    ):
        self.template_id = template_id
        self.steps = steps
        self.min_entropy_bits = min_entropy_bits
        self.description = description
    
    def calculate_entropy(self) -> float:
        """
        Calculate theoretical entropy in bits
        H = log2(N) where N is number of possible combinations
        """
        total_combinations = 1
        
        for step in self.steps:
            step_combinations = 1
            
            # Base action combinations
            if 'actions' in step:
                step_combinations *= len(step['actions'])
            
            # Direction combinations
            if 'directions' in step:
                step_combinations *= len(step['directions'])
            
            # Intensity combinations
            if 'intensities' in step:
                step_combinations *= len(step['intensities'])
            
            # Timing combinations
            if 'timings' in step:
                step_combinations *= len(step['timings'])
            
            # Sequence order combinations
            if 'sequence_length' in step:
                # For sequences, multiply by factorial
                import math
                step_combinations *= math.factorial(step['sequence_length'])
            
            total_combinations *= step_combinations
        
        # H = log2(N)
        entropy_bits = math.log2(total_combinations)
        
        return entropy_bits


# ============================================================================
# CHALLENGE TEMPLATE DEFINITIONS
# ============================================================================

CHALLENGE_TEMPLATES = {
    # Simple single-step challenges (LOW ENTROPY)
    "simple_turn": ChallengeTemplate(
        template_id="simple_turn",
        steps=[
            {
                "step": 1,
                "actions": [ChallengeType.HEAD_TURN],
                "directions": [Direction.LEFT, Direction.RIGHT],
                "intensities": [Intensity.NORMAL]
            }
        ],
        min_entropy_bits=1.0,  # log2(2) = 1 bit
        description="Simple head turn left or right"
    ),
    
    # Two-step sequence (MEDIUM ENTROPY)
    "two_step_sequence": ChallengeTemplate(
        template_id="two_step_sequence",
        steps=[
            {
                "step": 1,
                "actions": [ChallengeType.HEAD_TURN, ChallengeType.BLINK, ChallengeType.NOD],
                "directions": [Direction.LEFT, Direction.RIGHT],
            },
            {
                "step": 2,
                "actions": [ChallengeType.MOUTH, ChallengeType.EYEBROW, ChallengeType.SMILE],
            }
        ],
        min_entropy_bits=4.58,  # log2(6 * 3) = 4.58 bits
        description="Two-step sequential challenge"
    ),
    
    # Three-step with timing (HIGH ENTROPY)
    "three_step_timed": ChallengeTemplate(
        template_id="three_step_timed",
        steps=[
            {
                "step": 1,
                "actions": [ChallengeType.HEAD_TURN],
                "directions": [Direction.LEFT, Direction.RIGHT, Direction.UP, Direction.DOWN],
                "timings": [Timing.FAST, Timing.NORMAL, Timing.SLOW]
            },
            {
                "step": 2,
                "actions": [ChallengeType.BLINK, ChallengeType.WINK],
                "intensities": [Intensity.SUBTLE, Intensity.NORMAL, Intensity.EXAGGERATED]
            },
            {
                "step": 3,
                "actions": [ChallengeType.MOUTH, ChallengeType.SMILE, ChallengeType.FROWN],
                "directions": [Direction.LEFT, Direction.RIGHT]
            }
        ],
        min_entropy_bits=8.9,  # log2(4*3 * 2*3 * 3*2) = 8.9 bits
        description="Three-step timed challenge with variations"
    ),
    
    # Multi-step combinatorial (VERY HIGH ENTROPY)
    "combinatorial_challenge": ChallengeTemplate(
        template_id="combinatorial_challenge",
        steps=[
            {
                "step": 1,
                "actions": [
                    ChallengeType.HEAD_TURN, 
                    ChallengeType.BLINK,
                    ChallengeType.NOD,
                    ChallengeType.EYEBROW
                ],
                "directions": [Direction.LEFT, Direction.RIGHT, Direction.UP, Direction.DOWN],
                "intensities": [Intensity.SUBTLE, Intensity.NORMAL, Intensity.EXAGGERATED],
                "timings": [Timing.FAST, Timing.NORMAL, Timing.SLOW]
            },
            {
                "step": 2,
                "actions": [
                    ChallengeType.MOUTH,
                    ChallengeType.SMILE,
                    ChallengeType.FROWN,
                    ChallengeType.TONGUE
                ],
                "directions": [Direction.LEFT, Direction.RIGHT],
                "intensities": [Intensity.SUBTLE, Intensity.NORMAL, Intensity.EXAGGERATED]
            },
            {
                "step": 3,
                "actions": [
                    ChallengeType.WINK,
                    ChallengeType.BLINK,
                    ChallengeType.EYEBROW
                ],
                "intensities": [Intensity.SUBTLE, Intensity.NORMAL]
            },
            {
                "step": 4,
                "actions": [
                    ChallengeType.HEAD_TURN,
                    ChallengeType.NOD
                ],
                "directions": [Direction.LEFT, Direction.RIGHT, Direction.UP, Direction.DOWN],
                "timings": [Timing.FAST, Timing.NORMAL, Timing.SLOW]
            }
        ],
        min_entropy_bits=17.58,  # log2(4*4*3*3 * 4*2*3 * 3*2 * 2*4*3) = 17.58 bits
        description="Four-step combinatorial challenge"
    ),
    
    # Mega combinatorial (MAXIMUM ENTROPY)
    "mega_combinatorial": ChallengeTemplate(
        template_id="mega_combinatorial",
        steps=[
            {
                "step": 1,
                "actions": list(ChallengeType),  # All 9 actions
                "directions": list(Direction),    # All 4 directions
                "intensities": list(Intensity),   # All 3 intensities
                "timings": list(Timing)          # All 3 timings
            },
            {
                "step": 2,
                "actions": list(ChallengeType),
                "directions": list(Direction),
                "intensities": list(Intensity)
            },
            {
                "step": 3,
                "actions": list(ChallengeType),
                "directions": list(Direction),
                "timings": list(Timing)
            },
            {
                "step": 4,
                "actions": list(ChallengeType),
                "intensities": list(Intensity),
                "timings": list(Timing)
            },
            {
                "step": 5,
                "actions": list(ChallengeType),
                "directions": list(Direction)
            }
        ],
        min_entropy_bits=28.4,  # log2(9*4*3*3 * 9*4*3 * 9*4*3 * 9*3*3 * 9*4) = 28.4 bits
        description="Five-step mega combinatorial challenge"
    )
}


class ChallengeGenerator:
    """
    Cryptographically secure challenge generator
    Uses secrets module for CSPRNG
    """
    
    def __init__(self):
        self.templates = CHALLENGE_TEMPLATES
        self.generation_count = 0
        self.entropy_log = []
    
    def _secure_choice(self, options: List[Any]) -> Any:
        """Cryptographically secure random choice"""
        if not options:
            raise ValueError("Options list cannot be empty")
        
        # Use secrets.choice for cryptographic randomness
        return secrets.choice(options)
    
    def _secure_sample(self, options: List[Any], k: int) -> List[Any]:
        """Cryptographically secure random sample without replacement"""
        if k > len(options):
            raise ValueError("Sample size cannot exceed population size")
        
        # Use secrets.SystemRandom for cryptographic randomness
        rng = secrets.SystemRandom()
        return rng.sample(options, k)
    
    def generate_challenge_from_template(
        self,
        template: ChallengeTemplate,
        device_id: str,
        session_salt: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Generate a specific challenge instance from template
        Uses CSPRNG for all random selections
        """
        
        # Generate session salt if not provided
        if not session_salt:
            session_salt = secrets.token_hex(32)
        
        challenge_steps = []
        total_combinations = 1
        
        for step_template in template.steps:
            step_data = {
                "step_number": step_template["step"]
            }
            
            # Select action
            if "actions" in step_template:
                action = self._secure_choice(step_template["actions"])
                step_data["action"] = action.value
                total_combinations *= len(step_template["actions"])
            
            # Select direction (if applicable)
            if "directions" in step_template:
                direction = self._secure_choice(step_template["directions"])
                step_data["direction"] = direction.value
                total_combinations *= len(step_template["directions"])
            
            # Select intensity (if applicable)
            if "intensities" in step_template:
                intensity = self._secure_choice(step_template["intensities"])
                step_data["intensity"] = intensity.value
                total_combinations *= len(step_template["intensities"])
            
            # Select timing (if applicable)
            if "timings" in step_template:
                timing = self._secure_choice(step_template["timings"])
                step_data["timing"] = timing.value
                total_combinations *= len(step_template["timings"])
            
            challenge_steps.append(step_data)
        
        # Calculate actual entropy for this instance
        actual_entropy = math.log2(total_combinations)
        
        # Generate challenge ID with cryptographic randomness
        challenge_id = f"ch_{secrets.token_urlsafe(16)}"
        
        # Create instruction string
        instruction = self._generate_instruction(challenge_steps)
        
        challenge = {
            "challenge_id": challenge_id,
            "template_id": template.template_id,
            "steps": challenge_steps,
            "instruction": instruction,
            "entropy_bits": actual_entropy,
            "total_combinations": total_combinations,
            "session_salt": session_salt,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        # Log entropy
        self.entropy_log.append({
            "challenge_id": challenge_id,
            "template_id": template.template_id,
            "entropy_bits": actual_entropy,
            "timestamp": datetime.utcnow().isoformat()
        })
        
        self.generation_count += 1
        
        return challenge
    
    def _generate_instruction(self, steps: List[Dict[str, Any]]) -> str:
        """Generate human-readable instruction from steps"""
        
        if len(steps) == 1:
            return self._step_to_text(steps[0])
        
        # Multi-step instruction
        instruction_parts = []
        for i, step in enumerate(steps, 1):
            step_text = self._step_to_text(step)
            instruction_parts.append(f"Step {i}: {step_text}")
        
        return " → ".join(instruction_parts)
    
    def _step_to_text(self, step: Dict[str, Any]) -> str:
        """Convert step data to human-readable text"""
        
        action = step.get("action", "")
        direction = step.get("direction", "")
        intensity = step.get("intensity", "")
        timing = step.get("timing", "")
        
        # Build instruction
        parts = []
        
        # Timing prefix
        if timing == "fast":
            parts.append("Quickly")
        elif timing == "slow":
            parts.append("Slowly")
        
        # Intensity modifier
        if intensity == "subtle":
            parts.append("slightly")
        elif intensity == "exaggerated":
            parts.append("dramatically")
        
        # Action
        action_text = {
            "head_turn": "turn your head",
            "blink": "blink",
            "nod": "nod your head",
            "mouth": "open your mouth",
            "eyebrow": "raise your eyebrows",
            "smile": "smile",
            "frown": "frown",
            "tongue": "stick out your tongue",
            "wink": "wink"
        }.get(action, action)
        
        parts.append(action_text)
        
        # Direction
        if direction:
            parts.append(direction)
        
        return " ".join(parts)
    
    def generate_session_challenges(
        self,
        device_id: str,
        trust_level: str = "unknown",
        target_entropy_bits: float = 20.0
    ) -> List[Dict[str, Any]]:
        """
        Generate challenges for a session targeting minimum entropy
        
        Args:
            device_id: Device fingerprint
            trust_level: "high", "medium", "low", "unknown"
            target_entropy_bits: Minimum total entropy (default 20 bits)
        
        Returns:
            List of challenges that meet entropy target
        """
        
        # Determine number of challenges based on trust level
        if trust_level == "high":
            num_challenges = 1
            preferred_templates = ["two_step_sequence", "three_step_timed"]
        elif trust_level == "medium":
            num_challenges = 2
            preferred_templates = ["two_step_sequence", "three_step_timed", "combinatorial_challenge"]
        else:  # low or unknown
            num_challenges = 2
            preferred_templates = ["three_step_timed", "combinatorial_challenge", "mega_combinatorial"]
        
        # Generate session salt
        session_salt = secrets.token_hex(32)
        
        challenges = []
        cumulative_entropy = 0.0
        
        for i in range(num_challenges):
            # Select template based on remaining entropy needed
            remaining_entropy = target_entropy_bits - cumulative_entropy
            
            # Choose template that contributes to target
            suitable_templates = [
                template for template in preferred_templates
                if self.templates[template].min_entropy_bits <= remaining_entropy * 1.5
            ]
            
            if not suitable_templates:
                suitable_templates = preferred_templates
            
            template_id = self._secure_choice(suitable_templates)
            template = self.templates[template_id]
            
            # Generate challenge
            challenge = self.generate_challenge_from_template(
                template,
                device_id,
                session_salt
            )
            
            challenges.append(challenge)
            cumulative_entropy += challenge["entropy_bits"]
        
        # Verify entropy target met
        if cumulative_entropy < target_entropy_bits:
            # Add one more high-entropy challenge
            mega_template = self.templates["mega_combinatorial"]
            extra_challenge = self.generate_challenge_from_template(
                mega_template,
                device_id,
                session_salt
            )
            challenges.append(extra_challenge)
            cumulative_entropy += extra_challenge["entropy_bits"]
        
        return challenges
    
    def calculate_session_entropy(self, challenges: List[Dict[str, Any]]) -> float:
        """Calculate total session entropy"""
        return sum(c["entropy_bits"] for c in challenges)
    
    def get_entropy_statistics(self) -> Dict[str, Any]:
        """Get entropy generation statistics"""
        if not self.entropy_log:
            return {
                "total_challenges": 0,
                "avg_entropy_bits": 0,
                "min_entropy_bits": 0,
                "max_entropy_bits": 0
            }
        
        entropies = [log["entropy_bits"] for log in self.entropy_log]
        
        return {
            "total_challenges": len(self.entropy_log),
            "avg_entropy_bits": sum(entropies) / len(entropies),
            "min_entropy_bits": min(entropies),
            "max_entropy_bits": max(entropies),
            "template_distribution": self._get_template_distribution()
        }
    
    def _get_template_distribution(self) -> Dict[str, int]:
        """Get distribution of template usage"""
        distribution = {}
        for log in self.entropy_log:
            template_id = log["template_id"]
            distribution[template_id] = distribution.get(template_id, 0) + 1
        return distribution