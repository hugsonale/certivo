import uuid
import random

CHALLENGES = [
    "Blink twice",
    "Turn your head left",
    "Smile briefly",
    "Raise your eyebrows"
]

def generate_challenges(num=3):
    selected = random.sample(CHALLENGES, num)
    challenges = []

    for text in selected:
        challenges.append({
            "challenge_id": str(uuid.uuid4()),
            "challenge_type": "visual",
            "challenge_value": text
        })

    return challenges
