# challenge_engine.py — Adaptive Challenge Engine for Certivo Prime

import uuid
import random

# -------------------- CHALLENGE TEMPLATES --------------------
CHALLENGE_TEMPLATES = {
    "easy": ["Smile once", "Blink once", "Turn head left", "Say 'Hi'"],
    "medium": ["Smile twice", "Blink twice", "Turn head both sides", "Say 'Hello there'"],
    "hard": ["Smile and turn head", "Blink rapidly twice", "Rotate head full circle", "Say 'Verification challenge'"]
}

CHALLENGE_TYPES = ["smile", "blink", "head_turn", "say_phrase"]

# -------------------- GENERATE ADAPTIVE CHALLENGES --------------------
def generate_adaptive_challenges(prev_results=None, num=3, trusted=False):
    """
    Generates adaptive challenges based on previous results and trust status.

    prev_results: list of previous challenge results
    num: number of challenges to generate
    trusted: if device is trusted, can generate easier challenges
    """
    challenges = []

    # Compute average previous trust score if available
    avg_score = None
    if prev_results:
        avg_score = sum(r.get("liveness_score", 0) for r in prev_results) / len(prev_results)

    for _ in range(num):
        # Determine difficulty
        difficulty = "medium"
        if avg_score is not None:
            if avg_score > 0.8:
                difficulty = "hard"
            elif avg_score < 0.5:
                difficulty = "easy"

        # Trusted devices get easier challenges sometimes
        if trusted:
            difficulty = random.choice(["easy", "medium"])

        # Pick challenge type and value
        challenge_type = random.choice(CHALLENGE_TYPES)
        challenge_value = random.choice(CHALLENGE_TEMPLATES[difficulty])

        challenges.append({
            "challenge_id": str(uuid.uuid4()),
            "challenge_type": challenge_type,
            "challenge_value": challenge_value,
            "difficulty": difficulty,
            "fast_track": trusted
        })

    return challenges
