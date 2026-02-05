# human_verification.py
import os
import cv2
from logger import log_event

MIN_VIDEO_FRAMES = 3
MOTION_THRESHOLD = 0.2

# Fast-track thresholds (more lenient)
FAST_TRACK_MIN_FRAMES = 1
FAST_TRACK_MOTION_THRESHOLD = 0.15

def _video_motion_profile(video_path: str):
    """
    Analyzes video for motion with robust error handling.
    
    Returns:
        dict with {"frames": int, "total_motion": int} or None if error
    """
    if not os.path.exists(video_path):
        print(f"ERROR: Video file not found at {video_path}")
        return None
    
    cap = None
    try:
        cap = cv2.VideoCapture(video_path)
        
        # Check if video opened successfully
        if not cap.isOpened():
            print(f"ERROR: Could not open video file {video_path}")
            return None
        
        # Read first frame
        ret, prev = cap.read()
        if not ret or prev is None:
            print("ERROR: Could not read first frame")
            return None
        
        # Check frame dimensions
        if prev.shape[0] < 10 or prev.shape[1] < 10:
            print(f"ERROR: Frame dimensions too small: {prev.shape}")
            return None
        
        prev_gray = cv2.cvtColor(prev, cv2.COLOR_BGR2GRAY)
        total_motion = 0
        frames = 1
        
        while frames < 20:
            ret, frame = cap.read()
            if not ret or frame is None:
                break
            
            # Validate frame
            if frame.shape != prev.shape:
                print(f"WARNING: Frame {frames} has different dimensions, skipping")
                frames += 1
                continue
            
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            diff = cv2.absdiff(prev_gray, gray)
            
            if diff.mean() > MOTION_THRESHOLD:
                total_motion += 1
            
            prev_gray = gray
            frames += 1
        
        result = {"frames": frames, "total_motion": total_motion}
        print(f"DEBUG MOTION: {result}")
        return result
        
    except cv2.error as e:
        print(f"OpenCV ERROR in motion profile: {e}")
        return None
    except Exception as e:
        print(f"Unexpected ERROR in motion profile: {e}")
        return None
    finally:
        # Always release video capture
        if cap is not None:
            cap.release()


def run_human_verification(session_id: str, challenge_id: str, video_path: str, fast_track: bool = False):
    """
    Run human verification with optional fast-track mode.
    
    Args:
        session_id: Session identifier
        challenge_id: Challenge identifier
        video_path: Path to video file
        fast_track: If True, use more lenient thresholds
    
    Returns:
        dict: {"challenge_passed": bool, "liveness_score": float}
    """
    
    # Validate inputs
    if not session_id or not challenge_id:
        log_event(
            event="verification_input_error",
            session_id=session_id or "unknown",
            challenge_id=challenge_id or "unknown",
            details={"error": "Missing session_id or challenge_id"}
        )
        return {"liveness_score": 0.0, "challenge_passed": False}
    
    if not video_path or not os.path.exists(video_path):
        log_event(
            event="verification_input_error",
            session_id=session_id,
            challenge_id=challenge_id,
            details={"error": "Video path invalid or file does not exist", "path": video_path}
        )
        return {"liveness_score": 0.0, "challenge_passed": False}
    
    # Run motion analysis
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

    # Check if motion analysis failed
    if motion is None:
        log_event(
            event="challenge_failed",
            session_id=session_id,
            challenge_id=challenge_id,
            details={"reason": "motion_analysis_failed", "fast_track": fast_track}
        )
        return {"liveness_score": 0.0, "challenge_passed": False}
    
    # Use different thresholds based on fast-track status
    min_frames_required = FAST_TRACK_MIN_FRAMES if fast_track else MIN_VIDEO_FRAMES
    
    # Check if sufficient motion detected
    if motion["total_motion"] < min_frames_required:
        log_event(
            event="challenge_failed",
            session_id=session_id,
            challenge_id=challenge_id,
            details={
                "reason": "insufficient_motion",
                "fast_track": fast_track,
                "required_frames": min_frames_required,
                "actual_frames": motion["total_motion"]
            }
        )
        return {"liveness_score": 0.0, "challenge_passed": False}

    # Fast-track gets bonus liveness score
    liveness_score = 0.98 if fast_track else 0.95
    
    log_event(
        event="challenge_passed",
        session_id=session_id,
        challenge_id=challenge_id,
        details={
            "fast_track": fast_track,
            "liveness_score": liveness_score,
            "motion_frames": motion["total_motion"]
        }
    )
    
    return {
        "liveness_score": liveness_score,
        "challenge_passed": True
    }