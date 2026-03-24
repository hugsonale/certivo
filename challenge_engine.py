import uuid
import random
import time
import secrets
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

# ============================================================================
# CHALLENGE POOL - All 6 Types, 3 Difficulty Levels
# ============================================================================

EASY_CHALLENGES = [
    {"challenge_value": "Turn your head to the left", "difficulty": "easy", "expected_movement": "left"},
    {"challenge_value": "Turn your head to the right", "difficulty": "easy", "expected_movement": "right"},
    {"challenge_value": "Open your mouth wide", "difficulty": "easy", "expected_movement": "mouth"},
    {"challenge_value": "Blink twice", "difficulty": "easy", "expected_movement": "blink"},
]

MEDIUM_CHALLENGES = [
    {"challenge_value": "Nod your head up and down", "difficulty": "medium", "expected_movement": "nod"},
    {"challenge_value": "Raise your eyebrows", "difficulty": "medium", "expected_movement": "eyebrows"},
    {"challenge_value": "Turn your head to the left", "difficulty": "medium", "expected_movement": "left"},
    {"challenge_value": "Turn your head to the right", "difficulty": "medium", "expected_movement": "right"},
]

HARD_CHALLENGES = [
    {"challenge_value": "Nod your head up and down", "difficulty": "hard", "expected_movement": "nod"},
    {"challenge_value": "Blink twice slowly", "difficulty": "hard", "expected_movement": "blink"},
    {"challenge_value": "Raise your eyebrows high", "difficulty": "hard", "expected_movement": "eyebrows"},
    {"challenge_value": "Open your mouth wide", "difficulty": "hard", "expected_movement": "mouth"},
]

TRUSTED_CHALLENGES = [
    {"challenge_value": "Turn your head to the left", "difficulty": "easy", "expected_movement": "left"},
    {"challenge_value": "Turn your head to the right", "difficulty": "easy", "expected_movement": "right"},
    {"challenge_value": "Blink twice", "difficulty": "easy", "expected_movement": "blink"},
    {"challenge_value": "Open your mouth wide", "difficulty": "easy", "expected_movement": "mouth"},
]


def _calculate_difficulty_from_history(prev_results: list) -> str:
    if not prev_results:
        return "easy"

    recent = prev_results[-5:]
    passed = [r for r in recent if r.get("challenge_passed", False)]
    failed = [r for r in recent if not r.get("challenge_passed", False)]

    total = len(recent)
    pass_count = len(passed)
    fail_count = len(failed)

    last_two = recent[-2:]
    consecutive_failures = all(not r.get("challenge_passed", False) for r in last_two)

    last_three = recent[-3:]
    consecutive_passes = all(r.get("challenge_passed", False) for r in last_three)

    print(f"📊 Adaptive difficulty: {pass_count} passed, {fail_count} failed in last {total}")

    if consecutive_failures:
        print("⬇️  2+ failures → EASY")
        return "easy"

    if consecutive_passes and total >= 3:
        print("⬆️  3+ passes → HARD")
        return "hard"

    if pass_count >= 2 and fail_count == 0:
        print("⬆️  All recent passed → MEDIUM")
        return "medium"

    if fail_count >= 1:
        print("⬇️  Recent failure → EASY")
        return "easy"

    print("➡️  Mixed results → MEDIUM")
    return "medium"


def _get_pool_for_difficulty(difficulty: str) -> list:
    if difficulty == "hard":
        return HARD_CHALLENGES
    elif difficulty == "medium":
        return MEDIUM_CHALLENGES
    else:
        return EASY_CHALLENGES


def _pick_varied_challenges(pool: list, num: int, prev_results: list) -> list:
    recently_used = set()
    if prev_results:
        for r in prev_results[-3:]:
            movement = r.get("expected_movement") or r.get("action_detected")
            if movement:
                recently_used.add(movement)

    print(f"🔄 Recently used challenge types: {recently_used}")

    preferred = [c for c in pool if c["expected_movement"] not in recently_used]
    fallback = pool

    selected = []
    last_type = None

    for i in range(num):
        candidates = [c for c in (preferred if preferred else fallback)
                      if c["expected_movement"] != last_type]

        if not candidates:
            candidates = [c for c in fallback if c["expected_movement"] != last_type]

        if not candidates:
            candidates = fallback

        chosen = random.choice(candidates)
        selected.append(chosen)
        last_type = chosen["expected_movement"]

        preferred = [c for c in preferred if c["expected_movement"] != chosen["expected_movement"]]

    return selected


def generate_adaptive_challenges(
    device_id: str = None,
    trusted: bool = False,
    prev_results: list = None,
    num: int = None
) -> list:
    if prev_results is None:
        prev_results = []
    
    if device_id is None:
        device_id = f"dev_{int(time.time())}"
    
    if num is None:
        num = 1 if trusted else 2
    
    if trusted:
        pool = TRUSTED_CHALLENGES
        selected_raw = _pick_varied_challenges(pool, num, prev_results)
        difficulty_used = "easy"
        print(f"⚡ Trusted device — fast-track easy challenge(s)")
    else:
        difficulty_used = _calculate_difficulty_from_history(prev_results)
        pool = _get_pool_for_difficulty(difficulty_used)
        selected_raw = _pick_varied_challenges(pool, num, prev_results)
        print(f"🎯 Untrusted device — difficulty: {difficulty_used}")

    challenges = []
    for ch in selected_raw:
        challenge_id = f"chal_{device_id}_{int(time.time() * 1000)}_{secrets.token_hex(4)}"
        
        challenges.append({
            "challenge_id":      challenge_id,
            "challenge_value":   ch["challenge_value"],
            "difficulty":        ch["difficulty"],
            "expected_movement": ch["expected_movement"],
            "fast_track":        trusted,
        })

    types = [c["expected_movement"] for c in challenges]
    print(f"✅ Generated {len(challenges)} challenge(s): {types} | difficulty: {difficulty_used}")

    return challenges