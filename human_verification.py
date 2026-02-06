# human_verification.py
import os
import cv2
from logger import log_event

# Thresholds (VERY LENIENT FOR TESTING)
MIN_VIDEO_FRAMES = 1  # Was 3
MOTION_THRESHOLD = 0.1  # Was 0.2

# Fast-track thresholds (more lenient)
FAST_TRACK_MIN_FRAMES = 1
FAST_TRACK_MOTION_THRESHOLD = 0.1  # Was 0.15

# Direction detection thresholds
DIRECTION_THRESHOLD = 5  # pixels (was 15)
DIRECTION_CONFIDENCE_FRAMES = 1  # Must see direction for at least N frames (was 2)


def _detect_face_in_frame(frame):
    """
    Detect face in a single frame using Haar Cascade.
    Returns the face bounding box (x, y, w, h) or None.
    """
    try:
        # Load Haar Cascade for face detection
        face_cascade_path = cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
        face_cascade = cv2.CascadeClassifier(face_cascade_path)
        
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30))
        
        if len(faces) > 0:
            # Return the largest face (closest to camera)
            largest_face = max(faces, key=lambda face: face[2] * face[3])
            return largest_face
        return None
    except Exception as e:
        print(f"Face detection error: {e}")
        return None


def _analyze_head_movement_direction(video_path: str, expected_direction: str = None):
    """
    Analyzes video for head movement direction.
    
    Args:
        video_path: Path to video file
        expected_direction: "left" or "right" (or None to just detect any movement)
    
    Returns:
        dict with detailed analysis:
        {
            "frames_analyzed": int,
            "total_motion": int,
            "face_detected_frames": int,
            "direction_detected": str ("left", "right", "none", or "ambiguous"),
            "direction_confidence": float (0-1),
            "movement_magnitude": float,
            "direction_matches_expected": bool
        }
    """
    if not os.path.exists(video_path):
        print(f"ERROR: Video file not found at {video_path}")
        return None
    
    cap = None
    try:
        cap = cv2.VideoCapture(video_path)
        
        if not cap.isOpened():
            print(f"ERROR: Could not open video file {video_path}")
            return None
        
        # Read first frame
        ret, prev_frame = cap.read()
        if not ret or prev_frame is None:
            print("ERROR: Could not read first frame")
            return None
        
        prev_gray = cv2.cvtColor(prev_frame, cv2.COLOR_BGR2GRAY)
        
        # Track face positions across frames
        face_positions = []
        initial_face = _detect_face_in_frame(prev_frame)
        
        if initial_face is not None:
            face_positions.append({
                "frame": 0,
                "x": initial_face[0],
                "center_x": initial_face[0] + initial_face[2] / 2
            })
        
        frames_analyzed = 1
        total_motion = 0
        face_detected_frames = 1 if initial_face is not None else 0
        
        # Analyze subsequent frames
        while frames_analyzed < 30:  # Analyze up to 30 frames
            ret, frame = cap.read()
            if not ret or frame is None:
                break
            
            # Motion detection
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            diff = cv2.absdiff(prev_gray, gray)
            
            if diff.mean() > MOTION_THRESHOLD:
                total_motion += 1
            
            # Face tracking
            face = _detect_face_in_frame(frame)
            
            # DEBUG: Draw rectangle on face if detected
            if face is not None:
                x, y, w, h = face
                cv2.rectangle(frame, (x, y), (x+w, y+h), (0, 255, 0), 2)
                cv2.putText(frame, f"Frame {frames_analyzed}", (10, 30), 
                            cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
                
                face_detected_frames += 1
                face_positions.append({
                    "frame": frames_analyzed,
                    "x": face[0],
                    "center_x": face[0] + face[2] / 2
                })
            
            prev_gray = gray
            frames_analyzed += 1
        
        # Analyze collected face positions to determine direction
        direction_detected = "none"
        direction_confidence = 0.0
        movement_magnitude = 0.0
        
        if len(face_positions) >= 2:
            # Calculate average movement direction
            movements = []
            
            for i in range(1, len(face_positions)):
                delta_x = face_positions[i]["center_x"] - face_positions[i-1]["center_x"]
                movements.append(delta_x)
            
            # Calculate net movement
            net_movement = sum(movements)
            movement_magnitude = abs(net_movement)
            
            # Count directional consistency
            left_movements = sum(1 for m in movements if m < -DIRECTION_THRESHOLD)
            right_movements = sum(1 for m in movements if m > DIRECTION_THRESHOLD)
            
            total_directional_movements = left_movements + right_movements
            
            # Determine direction (account for webcam mirroring)
            if movement_magnitude > DIRECTION_THRESHOLD:
                # Swap left and right because webcam is mirrored
                if left_movements > right_movements and left_movements >= DIRECTION_CONFIDENCE_FRAMES:
                    direction_detected = "right"  # Swapped from "left"
                    direction_confidence = left_movements / max(total_directional_movements, 1)
                elif right_movements > left_movements and right_movements >= DIRECTION_CONFIDENCE_FRAMES:
                    direction_detected = "left"  # Swapped from "right"
                    direction_confidence = right_movements / max(total_directional_movements, 1)
                elif left_movements == right_movements and total_directional_movements > 0:
                    direction_detected = "ambiguous"
                    direction_confidence = 0.5
            
            print(f"DIRECTION ANALYSIS: Net movement: {net_movement:.2f}px, "
                  f"Left movements: {left_movements}, Right movements: {right_movements}, "
                  f"Detected: {direction_detected}, Confidence: {direction_confidence:.2f}")
        
        # Check if detected direction matches expected
        direction_matches_expected = False
        if expected_direction:
            expected_normalized = expected_direction.lower().strip()
            direction_matches_expected = (direction_detected == expected_normalized)
        
        result = {
            "frames_analyzed": frames_analyzed,
            "total_motion": total_motion,
            "face_detected_frames": face_detected_frames,
            "direction_detected": direction_detected,
            "direction_confidence": direction_confidence,
            "movement_magnitude": movement_magnitude,
            "direction_matches_expected": direction_matches_expected,
            "face_positions_tracked": len(face_positions)
        }
        
        print(f"DEBUG MOTION ANALYSIS: {result}")
        return result
        
    except cv2.error as e:
        print(f"OpenCV ERROR in motion analysis: {e}")
        return None
    except Exception as e:
        print(f"Unexpected ERROR in motion analysis: {e}")
        return None
    finally:
        if cap is not None:
            cap.release()


def run_human_verification(session_id: str, challenge_id: str, video_path: str, 
                           fast_track: bool = False, expected_direction: str = None):
    """
    Run human verification with direction validation.
    
    Args:
        session_id: Session identifier
        challenge_id: Challenge identifier
        video_path: Path to video file
        fast_track: If True, use more lenient thresholds
        expected_direction: "left" or "right" - the direction user was instructed to move
    
    Returns:
        dict: {
            "challenge_passed": bool,
            "liveness_score": float,
            "direction_detected": str,
            "direction_matched": bool
        }
    """
    
    # Validate inputs
    if not session_id or not challenge_id:
        log_event(
            event="verification_input_error",
            session_id=session_id or "unknown",
            challenge_id=challenge_id or "unknown",
            details={"error": "Missing session_id or challenge_id"}
        )
        return {
            "liveness_score": 0.0,
            "challenge_passed": False,
            "direction_detected": "none",
            "direction_matched": False
        }
    
    if not video_path or not os.path.exists(video_path):
        log_event(
            event="verification_input_error",
            session_id=session_id,
            challenge_id=challenge_id,
            details={"error": "Video path invalid or file does not exist", "path": video_path}
        )
        return {
            "liveness_score": 0.0,
            "challenge_passed": False,
            "direction_detected": "none",
            "direction_matched": False
        }
    
    # Run direction-aware motion analysis
    analysis = _analyze_head_movement_direction(video_path, expected_direction)
    
    log_event(
        event="signal_received",
        session_id=session_id,
        challenge_id=challenge_id,
        details={
            "frames_analyzed": analysis["frames_analyzed"] if analysis else 0,
            "total_motion": analysis["total_motion"] if analysis else 0,
            "face_detected_frames": analysis["face_detected_frames"] if analysis else 0,
            "direction_detected": analysis["direction_detected"] if analysis else "none",
            "direction_confidence": analysis["direction_confidence"] if analysis else 0.0,
            "expected_direction": expected_direction,
            "fast_track": fast_track
        }
    )

    # Check if analysis failed
    if analysis is None:
        log_event(
            event="challenge_failed",
            session_id=session_id,
            challenge_id=challenge_id,
            details={"reason": "motion_analysis_failed", "fast_track": fast_track}
        )
        return {
            "liveness_score": 0.0,
            "challenge_passed": False,
            "direction_detected": "none",
            "direction_matched": False
        }
    
    # VERIFICATION LAYER 1: Sufficient motion detected
    min_frames_required = FAST_TRACK_MIN_FRAMES if fast_track else MIN_VIDEO_FRAMES
    
    if analysis["total_motion"] < min_frames_required:
        log_event(
            event="challenge_failed",
            session_id=session_id,
            challenge_id=challenge_id,
            details={
                "reason": "insufficient_motion",
                "fast_track": fast_track,
                "required_frames": min_frames_required,
                "actual_frames": analysis["total_motion"]
            }
        )
        return {
            "liveness_score": 0.0,
            "challenge_passed": False,
            "direction_detected": analysis["direction_detected"],
            "direction_matched": False
        }
    
    # VERIFICATION LAYER 2: Face must be present during motion
    min_face_frames = 1 if fast_track else 2  # Lowered from 2/3
    
    if analysis["face_detected_frames"] < min_face_frames:
        log_event(
            event="challenge_failed",
            session_id=session_id,
            challenge_id=challenge_id,
            details={
                "reason": "insufficient_face_presence",
                "fast_track": fast_track,
                "required_face_frames": min_face_frames,
                "actual_face_frames": analysis["face_detected_frames"]
            }
        )
        return {
            "liveness_score": 0.0,
            "challenge_passed": False,
            "direction_detected": analysis["direction_detected"],
            "direction_matched": False
        }
    
    # VERIFICATION LAYER 3: Direction must match expected (if specified)
    if expected_direction:
        if not analysis["direction_matches_expected"]:
            log_event(
                event="challenge_failed",
                session_id=session_id,
                challenge_id=challenge_id,
                details={
                    "reason": "direction_mismatch",
                    "expected_direction": expected_direction,
                    "detected_direction": analysis["direction_detected"],
                    "direction_confidence": analysis["direction_confidence"]
                }
            )
            return {
                "liveness_score": 0.0,
                "challenge_passed": False,
                "direction_detected": analysis["direction_detected"],
                "direction_matched": False
            }
        
        # Check direction confidence
        min_confidence = 0.3 if fast_track else 0.4  # Lowered from 0.5/0.6
        
        if analysis["direction_confidence"] < min_confidence:
            log_event(
                event="challenge_failed",
                session_id=session_id,
                challenge_id=challenge_id,
                details={
                    "reason": "low_direction_confidence",
                    "required_confidence": min_confidence,
                    "actual_confidence": analysis["direction_confidence"]
                }
            )
            return {
                "liveness_score": 0.0,
                "challenge_passed": False,
                "direction_detected": analysis["direction_detected"],
                "direction_matched": True  # Direction was correct but confidence too low
            }
    
    # ALL CHECKS PASSED - Calculate liveness score
    base_score = 0.98 if fast_track else 0.95
    
    # Bonus for high direction confidence
    confidence_bonus = analysis["direction_confidence"] * 0.05
    liveness_score = min(1.0, base_score + confidence_bonus)
    
    log_event(
        event="challenge_passed",
        session_id=session_id,
        challenge_id=challenge_id,
        details={
            "fast_track": fast_track,
            "liveness_score": liveness_score,
            "motion_frames": analysis["total_motion"],
            "face_frames": analysis["face_detected_frames"],
            "direction_detected": analysis["direction_detected"],
            "direction_confidence": analysis["direction_confidence"],
            "direction_matched": analysis["direction_matches_expected"]
        }
    )
    
    return {
        "liveness_score": liveness_score,
        "challenge_passed": True,
        "direction_detected": analysis["direction_detected"],
        "direction_matched": analysis.get("direction_matches_expected", True)
    }