# challenge_engine.py

import uuid
import random

def generate_adaptive_challenges(prev_results=None, num=3, trusted=False):
    """
    Generate challenges with adaptive difficulty based on previous results.
    Trusted devices get easier/faster challenges (fast-track).
    Challenge types are aligned with human_verification.py expectations.
    """
    challenges = []

    # Determine difficulty based on previous results
    avg_score = None
    if prev_results:
        avg_score = sum(r.get("liveness_score", 0) for r in prev_results) / len(prev_results)

    for _ in range(num):
        # Base difficulty
        difficulty = "medium"
        if avg_score is not None:
            if avg_score > 0.8:
                difficulty = "hard"
            elif avg_score < 0.5:
                difficulty = "easy"

        # Trusted devices adjustment
        if trusted:
            difficulty = random.choice(["easy", "medium"])  # easier/faster for fast-track

        # Valid challenge types compatible with human_verification.py
        challenge_type = random.choice(["smile", "blink", "head_turn", "speak_phrase", "nod"])

        # Map challenge instructions based on type and difficulty
        value_map = {
            "smile": {
                "easy": "Smile once",
                "medium": "Smile twice",
                "hard": "Smile and turn head"
            },
            "blink": {
                "easy": "Blink once",
                "medium": "Blink twice",
                "hard": "Blink rapidly twice"
            },
            "head_turn": {
                "easy": "Turn head left",
                "medium": "Turn head both sides",
                "hard": "Rotate head full circle"
            },
            "speak_phrase": {
                "easy": "Say 'Hi'",
                "medium": "Say 'Hello there'",
                "hard": "Say 'Verification challenge'"
            },
            "nod": {
                "easy": "Nod once",
                "medium": "Nod twice",
                "hard": "Nod repeatedly"
            }
        }

        challenges.append({
            "challenge_id": str(uuid.uuid4()),
            "challenge_type": challenge_type,
            "challenge_value": value_map[challenge_type][difficulty],
            "difficulty": difficulty,
            "fast_track": trusted
        })

    return challenges
