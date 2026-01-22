# challenge_engine.py
import uuid
import random
from datetime import datetime, timedelta

# ---------------- CHALLENGE STORAGE ----------------
# In-memory store for active challenge sessions
active_challenges = {}  # {device_id: {"index": int, "tokens": [token_list], "expiry": datetime}}

def generate_adaptive_challenges(prev_results=None, num=3, trusted=False, device_id=None):
    challenges = []
    avg_score = None
    if prev_results:
        avg_score = sum(r.get("liveness_score", 0) for r in prev_results)/len(prev_results)

    for _ in range(num):
        difficulty = "medium"
        if avg_score is not None:
            if avg_score > 0.8: difficulty = "hard"
            elif avg_score < 0.5: difficulty = "easy"
        if trusted:
            difficulty = random.choice(["easy", "medium"])

        challenge_type = random.choice(["smile","blink","head_turn","say_phrase"])
        value_map = {
            "easy": ["Smile once","Blink once","Turn head left","Say 'Hi'"],
            "medium": ["Smile twice","Blink twice","Turn head both sides","Say 'Hello there'"],
            "hard": ["Smile and turn head","Blink rapidly twice","Rotate head full circle","Say 'Verification challenge'"]
        }

        token = str(uuid.uuid4())  # unique token per challenge
        challenges.append({
            "challenge_id": str(uuid.uuid4()),
            "challenge_type": challenge_type,
            "challenge_value": random.choice(value_map[difficulty]),
            "difficulty": difficulty,
            "fast_track": trusted,
            "token": token
        })

    # Store challenge session server-side for integrity
    if device_id:
        active_challenges[device_id] = {
            "index": 0,
            "tokens": [ch["token"] for ch in challenges],
            "expiry": datetime.utcnow() + timedelta(minutes=10)
        }

    return challenges

def verify_challenge_token(device_id, token):
    """Check if token is valid and in correct order"""
    session = active_challenges.get(device_id)
    if not session:
        return False, "No active session"

    if session["expiry"] < datetime.utcnow():
        del active_challenges[device_id]
        return False, "Session expired"

    # Check token order
    if session["index"] >= len(session["tokens"]):
        return False, "All challenges completed"

    expected_token = session["tokens"][session["index"]]
    if token != expected_token:
        return False, "Invalid token or out of order"

    # Token valid, increment index
    session["index"] += 1
    return True, "Valid"
