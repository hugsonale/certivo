import uuid
import random

def generate_adaptive_challenges(prev_results=[], num=3, trusted=False):
    """
    Generates a list of head-movement-only challenges for MVP v1.

    Supported challenges:
    - Turn head left
    - Turn head right
    """

    # ONLY supported challenges for now
    base_challenges = [
        {
            "challenge_value": "Turn your head to the left",
            "difficulty": "easy",
            "type": "head_movement",
            "direction": "left"
        },
        {
            "challenge_value": "Turn your head to the right",
            "difficulty": "easy",
            "type": "head_movement",
            "direction": "right"
        }
    ]

    # For MVP, trusted vs untrusted makes no difference yet
    adjusted_pool = base_challenges

    # Pick challenges (allow repetition if num > pool size)
    selected = random.choices(adjusted_pool, k=num)

    # Assign unique challenge_id
    challenges = []
    for ch in selected:
        challenges.append({
            "challenge_id": str(uuid.uuid4()),
            "challenge_value": ch["challenge_value"],
            "difficulty": ch["difficulty"],
            "type": ch["type"],
            "direction": ch["direction"]
        })

    return challenges
