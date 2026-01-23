# human_verification.py
import os
import cv2
from logger import log_event

MIN_VIDEO_FRAMES = 5
MOTION_THRESHOLD = 1.5

def _video_motion_profile(video_path: str):
    if not os.path.exists(video_path):
        return None
    cap = cv2.VideoCapture(video_path)
    ret, prev = cap.read()
    if not ret:
        cap.release()
        return None
    prev_gray = cv2.cvtColor(prev, cv2.COLOR_BGR2GRAY)
    total_motion = 0
    frames = 1
    while frames < 20:
        ret, frame = cap.read()
        if not ret:
            break
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        diff = cv2.absdiff(prev_gray, gray)
        if diff.mean() > MOTION_THRESHOLD:
            total_motion += 1
        prev_gray = gray
        frames += 1
    cap.release()
    return {"frames": frames, "total_motion": total_motion}

def run_human_verification(session_id, challenge_id, video_path: str):
    motion = _video_motion_profile(video_path)
    log_event(
        event="signal_received",
        session_id=session_id,
        challenge_id=challenge_id,
        details={"frames": motion["frames"] if motion else 0, "total_motion": motion["total_motion"] if motion else 0}
    )

    if not motion or motion["total_motion"] < MIN_VIDEO_FRAMES:
        log_event(event="challenge_failed", session_id=session_id, challenge_id=challenge_id, details={"reason": "insufficient_motion"})
        return {"liveness_score": 0.0, "challenge_passed": False}

    log_event(event="challenge_passed", session_id=session_id, challenge_id=challenge_id)
    return {"liveness_score": 0.95, "challenge_passed": True}
