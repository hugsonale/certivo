import uuid
import random

def generate_adaptive_challenges(prev_results=None, num=2, trusted=False):
    """
    Generates simple, reliable head-movement challenges with RANDOMIZATION.
    
    NEW IN 10/10:
    - Random timing windows (2-4 seconds)
    - Randomized challenge phrasing
    - Unpredictable order (already working)
    """

    if prev_results is None:
        prev_results = []

    # ============================================================================
    # RANDOMIZED CHALLENGE POOL - 10/10
    # ============================================================================
    
    # Left movement variants
    left_variants = [
        "Turn your head to the left",
        "Move your head left",
        "Look to the left",
        "Tilt your head left",
        "Turn left"
    ]
    
    # Right movement variants
    right_variants = [
        "Turn your head to the right",
        "Move your head right",
        "Look to the right",
        "Tilt your head right",
        "Turn right"
    ]
    
    base_challenges = [
        {
            "challenge_value": random.choice(left_variants),  # ← RANDOMIZED
            "difficulty": "easy",
            "expected_movement": "left",
            "timer_duration": random.randint(2, 4)  # ← RANDOMIZED (2-4 seconds)
        },
        {
            "challenge_value": random.choice(right_variants),  # ← RANDOMIZED
            "difficulty": "easy",
            "expected_movement": "right",
            "timer_duration": random.randint(2, 4)  # ← RANDOMIZED (2-4 seconds)
        }
    ]

    # Trusted devices still use same pool
    adjusted_pool = base_challenges

    # Pick challenges (random order)
    selected = random.choices(adjusted_pool, k=num)

    challenges = []
    for ch in selected:
        challenges.append({
            "challenge_id": str(uuid.uuid4()),
            "challenge_value": ch["challenge_value"],
            "difficulty": ch["difficulty"],
            "expected_movement": ch["expected_movement"],
            "timer_duration": ch["timer_duration"]  # ← NEW FIELD
        })

    return challenges