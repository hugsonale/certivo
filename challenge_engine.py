import uuid
import random

def generate_adaptive_challenges(prev_results=None, num=2, trusted=False):
    """
    Generates simple, reliable head-movement challenges ONLY.

    Allowed challenges:
    - Move head to the left
    - Move head to the right
    """

    if prev_results is None:
        prev_results = []

    # STRICT challenge pool (movement-only)
    base_challenges = [
        
        {
        "challenge_value": "Turn your head to the left",
        "difficulty": "easy",
        "expected_movement": "left"
    },
    {
        "challenge_value": "Turn your head to the right",
        "difficulty": "easy",
        "expected_movement": "right"
    },
    {
        "challenge_value": "Blink twice",  # ← NEW
        "difficulty": "easy",
        "expected_movement": "blink"
    },
    {
        "challenge_value": "Smile naturally",  # ← NEW
        "difficulty": "easy",
        "expected_movement": "smile"
    },
    {
        "challenge_value": "Raise your eyebrows",  # ← NEW
        "difficulty": "medium",
        "expected_movement": "eyebrows"
    }

    ]

    # Trusted devices still use same pool for now
    adjusted_pool = base_challenges

    # Pick challenges (allow repetition if num > pool size)
    selected = random.choices(adjusted_pool, k=num)

    challenges = []
    for ch in selected:
        challenges.append({
            "challenge_id": str(uuid.uuid4()),
            "challenge_value": ch["challenge_value"],
            "difficulty": ch["difficulty"],
            "expected_movement": ch["expected_movement"]
        })

    return challenges
