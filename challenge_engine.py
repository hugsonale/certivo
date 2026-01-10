# challenge_engine.py

import uuid
import random

def generate_challenges(num=3, difficulty=None):
    challenges = []

    for _ in range(num):
        # Example challenge types
        challenge_type = random.choice(["smile", "blink", "head_turn", "say_phrase"])

        # Determine difficulty if not provided
        ch_difficulty = difficulty or random.choice(["easy", "medium", "hard"])

        # Adjust challenge value based on difficulty and type
        if challenge_type == "smile":
            if ch_difficulty == "easy":
                value = "Smile once"
            elif ch_difficulty == "medium":
                value = "Smile twice"
            else:  # hard
                value = "Smile and turn head"
        elif challenge_type == "blink":
            if ch_difficulty == "easy":
                value = "Blink once"
            elif ch_difficulty == "medium":
                value = "Blink twice"
            else:
                value = "Blink three times quickly"
        elif challenge_type == "head_turn":
            if ch_difficulty == "easy":
                value = "Turn head left"
            elif ch_difficulty == "medium":
                value = "Turn head left and right"
            else:
                value = "Turn head full circle slowly"
        else:  # say_phrase
            if ch_difficulty == "easy":
                value = "Say 'Hello'"
            elif ch_difficulty == "medium":
                value = "Say 'I am human'"
            else:
                value = "Say 'Certivo verification complete'"

        challenges.append({
            "challenge_id": str(uuid.uuid4()),
            "challenge_type": challenge_type,
            "challenge_value": value,
            "difficulty": ch_difficulty
        })

    return challenges
