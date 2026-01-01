# challenge_engine.py
import uuid
from datetime import datetime
import random

# Predefined challenge types and instructions
CHALLENGE_TYPES = [
    ("blink", "Blink once"),
    ("blink", "Blink twice"),
    ("head_turn", "Turn your head to the left"),
    ("head_turn", "Turn your head to the right"),
    ("head_turn", "Turn your head left then right"),
    ("speak_phrase", "Say clearly: 'I am human'"),
    ("speak_phrase", "Say clearly: 'Hello world'"),
    ("speak_phrase", "Say clearly: 'Certivo verification'"),
    ("smile", "Smile once"),
    ("raise_eyebrow", "Raise your right eyebrow"),
    ("raise_eyebrow", "Raise your left eyebrow"),
    ("nod", "Nod your head once"),
    ("shake_head", "Shake your head once"),
    ("open_mouth", "Open your mouth wide once"),
]

def generate_challenges(num=3):
    """
    Generate a list of random human verification challenges.
    Returns a list of dicts with:
    - challenge_id
    - challenge_type
    - challenge_value
    - created_at
    """
    challenges = []
    for _ in range(num):
        challenge_type, challenge_value = random.choice(CHALLENGE_TYPES)
        challenge_id = str(uuid.uuid4())
        created_at = datetime.utcnow().isoformat()
        challenges.append({
            "challenge_id": challenge_id,
            "challenge_type": challenge_type,
            "challenge_value": challenge_value,
            "created_at": created_at
        })
    return challenges
