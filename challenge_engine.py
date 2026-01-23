# challenge_engine.py
import uuid
import random
from logger import log_event

def generate_adaptive_challenges(session_id, prev_results=None, num=3, trusted=False):
    challenges = []
    avg_score = None
    if prev_results:
        avg_score = sum(r.get("liveness_score",0) for r in prev_results)/len(prev_results)

    for _ in range(num):
        difficulty = "medium"
        if avg_score is not None:
            if avg_score>0.8: difficulty="hard"
            elif avg_score<0.5: difficulty="easy"
        if trusted:
            difficulty=random.choice(["easy","medium"])

        challenge_type=random.choice(["smile","blink","head_turn","say_phrase"])
        value_map = {
            "easy":["Smile once","Blink once","Turn head left","Say 'Hi'"],
            "medium":["Smile twice","Blink twice","Turn head both sides","Say 'Hello there'"],
            "hard":["Smile and turn head","Blink rapidly twice","Rotate head full circle","Say 'Verification challenge'"]
        }
        challenge_value = random.choice(value_map[difficulty])
        challenge_id = str(uuid.uuid4())
        challenge = {
            "challenge_id": challenge_id,
            "challenge_type": challenge_type,
            "challenge_value": challenge_value,
            "difficulty": difficulty,
            "fast_track": trusted
        }
        challenges.append(challenge)

        # Log challenge issuance
        log_event(
            event="challenge_issued",
            session_id=session_id,
            challenge_id=challenge_id,
            details={"type": challenge_type, "instruction": challenge_value, "difficulty": difficulty}
        )
    return challenges
