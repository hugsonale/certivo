import uuid
import random

def generate_adaptive_challenges(prev_results=[], num=3, trusted=False):
    """
    Generates a list of challenges for a verification session.

    Parameters:
    - prev_results: List of previous challenge results (for adaptive logic)
    - num: Number of challenges to generate
    - trusted: Boolean, whether device is trusted (fast-track easier challenges)

    Returns:
    - List of dicts with challenge_id, challenge_value, difficulty
    """

    # Base pool of challenge instructions
    base_challenges = [
        {"challenge_value": "Blink your eyes twice quickly", "difficulty": "medium"},
        {"challenge_value": "Turn your head to the left then right", "difficulty": "medium"},
        {"challenge_value": "Say 'Certivo is secure' clearly", "difficulty": "hard"},
        {"challenge_value": "Smile widely for 3 seconds", "difficulty": "easy"},
        {"challenge_value": "Raise your eyebrows once", "difficulty": "easy"},
        {"challenge_value": "Open your mouth and say 'I am human'", "difficulty": "hard"},
        {"challenge_value": "Nod your head up and down", "difficulty": "medium"},
        {"challenge_value": "Stick your tongue out for 2 seconds", "difficulty": "easy"}
    ]

    # Adjust challenge pool for trusted devices (easier)
    if trusted:
        adjusted_pool = [ch for ch in base_challenges if ch["difficulty"] in ("easy", "medium")]
    else:
        adjusted_pool = base_challenges

    # Randomly pick `num` unique challenges
    selected = random.sample(adjusted_pool, k=min(num, len(adjusted_pool)))

    # Assign unique challenge_id to each
    for ch in selected:
        ch["challenge_id"] = str(uuid.uuid4())

    return selected
