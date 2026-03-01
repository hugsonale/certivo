"""
Test video processing speed
"""
import time
import sys
sys.path.insert(0, '.')

from human_verification import run_human_verification

# You'll need to provide a real video file path
VIDEO_PATH = "path/to/test/video.webm"  # Update this
SESSION_ID = "speed_test"
CHALLENGE_ID = "challenge_test"

print("⏱️  Testing video processing speed...")
print("=" * 60)

# Test 5 times and average
times = []

for i in range(5):
    start = time.time()
    
    result = run_human_verification(
        session_id=SESSION_ID,
        challenge_id=CHALLENGE_ID,
        video_path=VIDEO_PATH,
        fast_track=False,
        expected_movement="left"
    )
    
    end = time.time()
    processing_time = (end - start) * 1000
    times.append(processing_time)
    
    print(f"Run {i+1}: {processing_time:.2f}ms")

avg_time = sum(times) / len(times)
print("=" * 60)
print(f"Average processing time: {avg_time:.2f}ms")

if avg_time < 1000:
    print("✅ EXCELLENT - Under 1 second")
elif avg_time < 3000:
    print("✅ GOOD - Under 3 seconds")
else:
    print("⚠️  SLOW - Consider optimization")