# human_verification.py
import os
import cv2
from logger import log_event

# Regular thresholds
MIN_VIDEO_FRAMES = 3
MOTION_THRESHOLD = 0.2

# Fast-track thresholds (more lenient)
FAST_TRACK_MIN_FRAMES = 1
FAST_TRACK_MOTION_THRESHOLD = 0.15

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
    
    print("DEBUG MOTION:", {"frames": frames, "total_motion": total_motion})
    return {"frames": frames, "total_motion": total_motion}

def run_human_verification(session_id, challenge_id, video_path: str, fast_track=False):
    """
    Run human verification with optional fast-track mode.
    
    Args:
        session_id: Session identifier
        challenge_id: Challenge identifier
        video_path: Path to video file
        fast_track: If True, use more lenient thresholds
    """
    motion = _video_motion_profile(video_path)
    
    log_event(
        event="signal_received",
        session_id=session_id,
        challenge_id=challenge_id,
        details={
            "frames": motion["frames"] if motion else 0,
            "total_motion": motion["total_motion"] if motion else 0,
            "fast_track": fast_track
        }
    )

    # Use different thresholds based on fast-track status
    min_frames_required = FAST_TRACK_MIN_FRAMES if fast_track else MIN_VIDEO_FRAMES
    
    if not motion or motion["total_motion"] < min_frames_required:
        log_event(
            event="challenge_failed",
            session_id=session_id,
            challenge_id=challenge_id,
            details={
                "reason": "insufficient_motion",
                "fast_track": fast_track,
                "required_frames": min_frames_required,
                "actual_frames": motion["total_motion"] if motion else 0
            }
        )
        return {"liveness_score": 0.0, "challenge_passed": False}

    # Fast-track gets bonus liveness score
    liveness_score = 0.98 if fast_track else 0.95
    
    log_event(
        event="challenge_passed",
        session_id=session_id,
        challenge_id=challenge_id,
        details={"fast_track": fast_track}
    )
    
    return {"liveness_score": liveness_score, "challenge_passed": True}