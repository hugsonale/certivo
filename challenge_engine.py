import uuid
import random

def generate_adaptive_challenges(prev_results=None, num=2, trusted=False):
    """
    SIMPLIFIED: Only generate LEFT/RIGHT challenges (most reliable).
    
    We're focusing on stability first, can add more challenge types later.
    """
    
    if prev_results is None:
        prev_results = []
    
    # ============================================================================
    # ONLY LEFT/RIGHT CHALLENGES (Most Reliable)
    # ============================================================================
    
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
        }
    ]
    
    # Pick challenges randomly
    selected = random.choices(base_challenges, k=num)
    
    # Format challenges
    challenges = []
    for ch in selected:
        challenges.append({
            "challenge_id": str(uuid.uuid4()),
            "challenge_value": ch["challenge_value"],
            "difficulty": ch["difficulty"],
            "expected_movement": ch["expected_movement"],
            "fast_track": trusted
        })
    
    return challenges