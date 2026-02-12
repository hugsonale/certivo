import uuid
import random

# ============================================================================
# GLOBAL STATE: Track failed challenges per device
# ============================================================================
device_failure_count = {}


def generate_adaptive_challenges(prev_results=None, num=2, trusted=False, device_id=None):
    """
    Generates adaptive challenges with smart shuffling.
    
    - If 2 consecutive failures: shuffle to different challenge types
    - Ensures variety and prevents gaming the system
    
    Args:
        prev_results: List of previous challenge results
        num: Number of challenges to generate
        trusted: Whether device is trusted (affects difficulty)
        device_id: Device identifier for tracking failures
    
    Returns:
        List of challenge dicts
    """
    
    if prev_results is None:
        prev_results = []
    
    # ============================================================================
    # FULL CHALLENGE POOL - 6 Actions
    # ============================================================================
    all_challenges = [
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
            "challenge_value": "Nod your head",
            "difficulty": "medium",
            "expected_movement": "nod"
        },
        {
            "challenge_value": "Open your mouth",
            "difficulty": "easy",
            "expected_movement": "mouth"
        },
        {
            "challenge_value": "Raise your eyebrows",
            "difficulty": "medium",
            "expected_movement": "eyebrows"
        }
    ]
    
    # ============================================================================
    # FAILURE TRACKING & ADAPTIVE SELECTION
    # ============================================================================
    
    # Track failures for this device
    if device_id:
        if device_id not in device_failure_count:
            device_failure_count[device_id] = 0
        
        # Check if last 2 challenges failed
        if len(prev_results) >= 2:
            last_two = prev_results[-2:]
            if all(not r.get("challenge_passed", False) for r in last_two):
                device_failure_count[device_id] += 1
                print(f"⚠️ Device {device_id} has {device_failure_count[device_id]} consecutive failures")
    
    # ============================================================================
    # CHALLENGE SELECTION LOGIC
    # ============================================================================
    
    # Get previously used challenge types from this session
    used_types = set()
    if prev_results:
        for r in prev_results[-5:]:  # Last 5 challenges
            if "expected_movement" in r:
                used_types.add(r["expected_movement"])
    
    # If device has 2+ failures, force shuffle to unused challenge types
    if device_id and device_failure_count.get(device_id, 0) >= 1:
        print(f"🔄 Forcing challenge shuffle for device {device_id}")
        
        # Get unused challenge types
        unused_challenges = [ch for ch in all_challenges if ch["expected_movement"] not in used_types]
        
        if len(unused_challenges) >= num:
            # Use only unused challenges
            pool = unused_challenges
        else:
            # Not enough unused, use all challenges
            pool = all_challenges
        
        # Reset failure count after shuffle
        device_failure_count[device_id] = 0
    else:
        # Normal selection - prefer variety
        pool = all_challenges
    
    # ============================================================================
    # GENERATE CHALLENGES
    # ============================================================================
    
    selected = []
    available_pool = pool.copy()
    
    for i in range(num):
        if not available_pool:
            # Refresh pool if exhausted
            available_pool = pool.copy()
        
        # Pick random challenge
        challenge = random.choice(available_pool)
        
        # Remove from pool to avoid immediate repetition
        available_pool.remove(challenge)
        
        selected.append(challenge)
    
    # ============================================================================
    # FORMAT CHALLENGES
    # ============================================================================
    
    challenges = []
    for ch in selected:
        challenges.append({
            "challenge_id": str(uuid.uuid4()),
            "challenge_value": ch["challenge_value"],
            "difficulty": ch["difficulty"],
            "expected_movement": ch["expected_movement"],
            "fast_track": trusted
        })
    
    print(f"✅ Generated {num} challenges: {[ch['expected_movement'] for ch in challenges]}")
    
    return challenges


def reset_device_failures(device_id: str):
    """
    Reset failure count for a device (call after successful verification).
    """
    if device_id in device_failure_count:
        del device_failure_count[device_id]