import uuid
import random

# ============================================================================
# CHALLENGE POOL - All 6 Types, 3 Difficulty Levels
# ============================================================================

# EASY challenges - simple, quick to perform, high detection reliability
EASY_CHALLENGES = [
    {
        "challenge_value": "Turn your head to the left",
        "difficulty": "easy",
        "expected_movement": "left"
    },
    {
        "challenge_value": "Turn your head to the right",
        "difficulty": "easy",
        "expected_movement": "right"
    },
    {
        "challenge_value": "Open your mouth wide",
        "difficulty": "easy",
        "expected_movement": "mouth"
    },
    {
        "challenge_value": "Blink twice",
        "difficulty": "easy",
        "expected_movement": "blink"
    },
]

# MEDIUM challenges - slightly more effort, reliable detection
MEDIUM_CHALLENGES = [
    {
        "challenge_value": "Nod your head up and down",
        "difficulty": "medium",
        "expected_movement": "nod"
    },
    {
        "challenge_value": "Raise your eyebrows",
        "difficulty": "medium",
        "expected_movement": "eyebrows"
    },
    {
        "challenge_value": "Turn your head to the left",
        "difficulty": "medium",
        "expected_movement": "left"
    },
    {
        "challenge_value": "Turn your head to the right",
        "difficulty": "medium",
        "expected_movement": "right"
    },
]

# HARD challenges - combination or larger movement required
HARD_CHALLENGES = [
    {
        "challenge_value": "Nod your head up and down",
        "difficulty": "hard",
        "expected_movement": "nod"
    },
    {
        "challenge_value": "Blink twice slowly",
        "difficulty": "hard",
        "expected_movement": "blink"
    },
    {
        "challenge_value": "Raise your eyebrows high",
        "difficulty": "hard",
        "expected_movement": "eyebrows"
    },
    {
        "challenge_value": "Open your mouth wide",
        "difficulty": "hard",
        "expected_movement": "mouth"
    },
]

# TRUSTED DEVICE challenges - always easy, always fast, always reliable
TRUSTED_CHALLENGES = [
    {
        "challenge_value": "Turn your head to the left",
        "difficulty": "easy",
        "expected_movement": "left"
    },
    {
        "challenge_value": "Turn your head to the right",
        "difficulty": "easy",
        "expected_movement": "right"
    },
    {
        "challenge_value": "Blink twice",
        "difficulty": "easy",
        "expected_movement": "blink"
    },
    {
        "challenge_value": "Open your mouth wide",
        "difficulty": "easy",
        "expected_movement": "mouth"
    },
]


# ============================================================================
# ADAPTIVE DIFFICULTY ENGINE
# ============================================================================

def _calculate_difficulty_from_history(prev_results: list) -> str:
    """
    Analyse previous challenge results and decide what difficulty to use next.

    Rules:
    - No history                          → easy   (first-time user, be welcoming)
    - Last 1-2 results all passed         → medium (user is doing well, ramp up)
    - Last 3+ results all passed          → hard   (user is clearly capable)
    - Last result failed                  → easy   (struggling, give easier task)
    - 2+ consecutive failures             → easy   (keep it easy, don't frustrate)
    - Mixed pass/fail                     → medium (keep at current level)
    """

    if not prev_results:
        return "easy"

    # Only look at the last 5 results (recent history is most relevant)
    recent = prev_results[-5:]

    passed = [r for r in recent if r.get("challenge_passed", False)]
    failed = [r for r in recent if not r.get("challenge_passed", False)]

    total = len(recent)
    pass_count = len(passed)
    fail_count = len(failed)

    # Check last two for consecutive failures
    last_two = recent[-2:]
    consecutive_failures = all(not r.get("challenge_passed", False) for r in last_two)

    # Check last three for consecutive passes
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
    """Return the correct challenge pool for a given difficulty."""
    if difficulty == "hard":
        return HARD_CHALLENGES
    elif difficulty == "medium":
        return MEDIUM_CHALLENGES
    else:
        return EASY_CHALLENGES


def _pick_varied_challenges(pool: list, num: int, prev_results: list) -> list:
    """
    Pick `num` challenges from `pool` ensuring:
    1. No two consecutive challenges of the same type.
    2. Avoid repeating the most recently used challenge type.
    3. Cover as many different types as possible.
    """

    # Find recently used movement types (last 3)
    recently_used = set()
    if prev_results:
        for r in prev_results[-3:]:
            movement = r.get("expected_movement") or r.get("action_detected")
            if movement:
                recently_used.add(movement)

    print(f"🔄 Recently used challenge types: {recently_used}")

    # Prefer challenges NOT recently used
    preferred = [c for c in pool if c["expected_movement"] not in recently_used]
    fallback = pool  # Use full pool if preferred is too small

    selected = []
    last_type = None

    for i in range(num):
        # Build candidate list - avoid repeating last type
        candidates = [c for c in (preferred if preferred else fallback)
                      if c["expected_movement"] != last_type]

        # If candidates empty (all same type), open up to full pool
        if not candidates:
            candidates = [c for c in fallback if c["expected_movement"] != last_type]

        # Last resort: use entire pool
        if not candidates:
            candidates = fallback

        chosen = random.choice(candidates)
        selected.append(chosen)
        last_type = chosen["expected_movement"]

        # Remove chosen type from preferred to increase variety
        preferred = [c for c in preferred if c["expected_movement"] != chosen["expected_movement"]]

    return selected


# ============================================================================
# MAIN PUBLIC FUNCTION
# ============================================================================

def generate_adaptive_challenges(prev_results=None, num=2, trusted=False, device_id=None):
    """
    Generate adaptive challenges based on device trust and performance history.

    Args:
        prev_results : list  - Previous challenge result dicts from this session.
        num          : int   - Number of challenges to generate.
        trusted      : bool  - Whether this is a trusted (fast-track) device.
        device_id    : str   - Optional device identifier for logging.

    Returns:
        list of challenge dicts, each containing:
            challenge_id      : str  - Unique UUID
            challenge_value   : str  - Human-readable instruction
            difficulty        : str  - "easy" | "medium" | "hard"
            expected_movement : str  - "left"|"right"|"nod"|"blink"|"mouth"|"eyebrows"
            fast_track        : bool - Whether this is a fast-track challenge
    """

    if prev_results is None:
        prev_results = []

    # ------------------------------------------------------------------ #
    # TRUSTED DEVICES: Always easy, always 1 challenge, always fast-track #
    # ------------------------------------------------------------------ #
    if trusted:
        pool = TRUSTED_CHALLENGES
        selected_raw = _pick_varied_challenges(pool, num, prev_results)
        difficulty_used = "easy"
        print(f"⚡ Trusted device — fast-track easy challenge(s)")

    # ------------------------------------------------------------------ #
    # UNTRUSTED DEVICES: Adaptive difficulty                              #
    # ------------------------------------------------------------------ #
    else:
        difficulty_used = _calculate_difficulty_from_history(prev_results)
        pool = _get_pool_for_difficulty(difficulty_used)
        selected_raw = _pick_varied_challenges(pool, num, prev_results)
        print(f"🎯 Untrusted device — difficulty: {difficulty_used}")

    # ------------------------------------------------------------------ #
    # FORMAT OUTPUT                                                        #
    # ------------------------------------------------------------------ #
    challenges = []
    for ch in selected_raw:
        challenges.append({
            "challenge_id":      str(uuid.uuid4()),
            "challenge_value":   ch["challenge_value"],
            "difficulty":        ch["difficulty"],
            "expected_movement": ch["expected_movement"],
            "fast_track":        trusted,
        })

    # Log summary
    types = [c["expected_movement"] for c in challenges]
    print(f"✅ Generated {len(challenges)} challenge(s): {types} | difficulty: {difficulty_used}")

    return challenges