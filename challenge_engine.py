import uuid
import random

CHALLENGES = [
    {"type": "visual", "instruction": "Blink twice"},
    {"type": "visual", "instruction": "Turn your head left"},
    {"type": "visual", "instruction": "Smile briefly"},
    {"type": "visual", "instruction": "Raise your eyebrows"},
    {"type": "speak_phrase", "instruction": "Say 'Certivo is live'"}
]

def generate_challenges(num=3):
    selected = random.sample(CHALLENGES, num)
    challenges = []
    for ch in selected:
        challenges.append({
            "challenge_id": str(uuid.uuid4()),
            "challenge_type": ch["type"],
            "challenge_value": ch["instruction"]
        })
    return challenges
