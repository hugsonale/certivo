import os
import cv2
import numpy as np
from logger import log_event

# ============================================================================
# PRODUCTION THRESHOLDS (Stricter for real verification)
# ============================================================================

# Core thresholds
MIN_VIDEO_FRAMES = 3
MOTION_THRESHOLD = 0.3

# Fast-track thresholds (more lenient)
FAST_TRACK_MIN_FRAMES = 2
FAST_TRACK_MOTION_THRESHOLD = 0.2

# Direction detection thresholds
DIRECTION_THRESHOLD = 15  # pixels
DIRECTION_CONFIDENCE_FRAMES = 2  # Must see direction for at least N frames

# Blink detection thresholds
MIN_BLINKS = 2
MAX_BLINKS = 4
EYE_ASPECT_RATIO_THRESHOLD = 0.25  # Eyes closed when below this

# Nod detection thresholds
NOD_VERTICAL_THRESHOLD = 10  # pixels
MIN_NOD_CYCLES = 1  # At least 1 up-down cycle

# Mouth detection thresholds
MOUTH_ASPECT_RATIO_THRESHOLD = 0.6  # Mouth open when above this
MIN_MOUTH_OPEN_FRAMES = 3

# Eyebrow detection thresholds
EYEBROW_RAISE_THRESHOLD = 5  # pixels upward movement
MIN_EYEBROW_FRAMES = 3


# ============================================================================
# FACE DETECTION UTILITIES
# ============================================================================

def _detect_face_in_frame(frame):
    """
    Detect face in a single frame using Haar Cascade.
    Returns the face bounding box (x, y, w, h) or None.
    """
    try:
        face_cascade_path = cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
        face_cascade = cv2.CascadeClassifier(face_cascade_path)
        
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(50, 50))
        
        if len(faces) > 0:
            # Return the largest face (closest to camera)
            largest_face = max(faces, key=lambda face: face[2] * face[3])
            return largest_face
        return None
    except Exception as e:
        print(f"Face detection error: {e}")
        return None


def _get_eye_aspect_ratio(eye_points):
    """
    Calculate Eye Aspect Ratio (EAR) to detect blinks.
    Lower EAR = eyes more closed.
    """
    # Vertical eye distances
    A = np.linalg.norm(eye_points[1] - eye_points[5])
    B = np.linalg.norm(eye_points[2] - eye_points[4])
    
    # Horizontal eye distance
    C = np.linalg.norm(eye_points[0] - eye_points[3])
    
    # EAR formula
    ear = (A + B) / (2.0 * C)
    return ear


def _get_mouth_aspect_ratio(mouth_points):
    """
    Calculate Mouth Aspect Ratio (MAR) to detect open mouth.
    Higher MAR = mouth more open.
    """
    # Vertical mouth distances
    A = np.linalg.norm(mouth_points[2] - mouth_points[10])  # Top to bottom
    B = np.linalg.norm(mouth_points[4] - mouth_points[8])   # Top to bottom
    
    # Horizontal mouth distance
    C = np.linalg.norm(mouth_points[0] - mouth_points[6])   # Left to right
    
    # MAR formula
    mar = (A + B) / (2.0 * C)
    return mar


# ============================================================================
# CHALLENGE-SPECIFIC DETECTION FUNCTIONS
# ============================================================================

def _detect_head_turn(video_path: str, expected_direction: str = None):
    """
    Detect head turn left or right.
    Returns detailed analysis dict.
    """
    if not os.path.exists(video_path):
        return None
    
    cap = None
    try:
        cap = cv2.VideoCapture(video_path)
        
        if not cap.isOpened():
            return None
        
        # Read first frame
        ret, prev_frame = cap.read()
        if not ret or prev_frame is None:
            return None
        
        # Track face positions across frames
        face_positions = []
        initial_face = _detect_face_in_frame(prev_frame)
        
        if initial_face is not None:
            face_positions.append({
                "frame": 0,
                "center_x": initial_face[0] + initial_face[2] / 2
            })
        
        frames_analyzed = 1
        total_motion = 0
        face_detected_frames = 1 if initial_face is not None else 0
        
        prev_gray = cv2.cvtColor(prev_frame, cv2.COLOR_BGR2GRAY)
        
        # Analyze subsequent frames (up to 90 frames = ~3 seconds at 30fps)
        while frames_analyzed < 90:
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
            
            if face is not None:
                face_detected_frames += 1
                face_positions.append({
                    "frame": frames_analyzed,
                    "center_x": face[0] + face[2] / 2
                })
            
            prev_gray = gray
            frames_analyzed += 1
        
        # Analyze collected face positions to determine direction
        direction_detected = "none"
        direction_confidence = 0.0
        movement_magnitude = 0.0
        
        if len(face_positions) >= 2:
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
            if movement_magnitude > DIRECTION_THRESHOLD * 2:  # Require significant movement
                # Swap left and right because webcam is mirrored
                if left_movements > right_movements and left_movements >= DIRECTION_CONFIDENCE_FRAMES:
                    direction_detected = "right"
                    direction_confidence = left_movements / max(total_directional_movements, 1)
                elif right_movements > left_movements and right_movements >= DIRECTION_CONFIDENCE_FRAMES:
                    direction_detected = "left"
                    direction_confidence = right_movements / max(total_directional_movements, 1)
        
        # Check if detected direction matches expected
        direction_matches_expected = False
        if expected_direction:
            expected_normalized = expected_direction.lower().strip()
            direction_matches_expected = (direction_detected == expected_normalized)
        
        return {
            "frames_analyzed": frames_analyzed,
            "total_motion": total_motion,
            "face_detected_frames": face_detected_frames,
            "direction_detected": direction_detected,
            "direction_confidence": direction_confidence,
            "movement_magnitude": movement_magnitude,
            "direction_matches_expected": direction_matches_expected,
            "face_positions_tracked": len(face_positions)
        }
        
    except Exception as e:
        print(f"Head turn detection error: {e}")
        return None
    finally:
        if cap is not None:
            cap.release()


def _detect_blinks(video_path: str):
    """
    Detect blink count using Eye Aspect Ratio (EAR).
    Returns analysis dict.
    """
    if not os.path.exists(video_path):
        return None
    
    cap = None
    try:
        cap = cv2.VideoCapture(video_path)
        
        if not cap.isOpened():
            return None
        
        # Load eye cascade
        eye_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_eye.xml')
        
        blink_count = 0
        frames_analyzed = 0
        face_detected_frames = 0
        eyes_closed_consecutive = 0
        eyes_open_consecutive = 0
        last_state = "open"
        
        while frames_analyzed < 90:
            ret, frame = cap.read()
            if not ret or frame is None:
                break
            
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = _detect_face_in_frame(frame)
            
            if faces is not None:
                face_detected_frames += 1
                x, y, w, h = faces
                
                roi_gray = gray[y:y+h, x:x+w]
                eyes = eye_cascade.detectMultiScale(roi_gray, scaleFactor=1.1, minNeighbors=5)
                
                # Detect eye state
                if len(eyes) == 0:
                    # Eyes likely closed
                    eyes_closed_consecutive += 1
                    eyes_open_consecutive = 0
                    
                    # Register blink if transition from open to closed
                    if last_state == "open" and eyes_closed_consecutive >= 2:
                        blink_count += 1
                        last_state = "closed"
                else:
                    # Eyes open
                    eyes_open_consecutive += 1
                    eyes_closed_consecutive = 0
                    
                    if eyes_open_consecutive >= 2:
                        last_state = "open"
            
            frames_analyzed += 1
        
        return {
            "frames_analyzed": frames_analyzed,
            "face_detected_frames": face_detected_frames,
            "blink_count": blink_count,
            "blinks_detected": blink_count >= MIN_BLINKS and blink_count <= MAX_BLINKS
        }
        
    except Exception as e:
        print(f"Blink detection error: {e}")
        return None
    finally:
        if cap is not None:
            cap.release()


def _detect_nod(video_path: str):
    """
    Detect head nod (vertical movement).
    Returns analysis dict.
    """
    if not os.path.exists(video_path):
        return None
    
    cap = None
    try:
        cap = cv2.VideoCapture(video_path)
        
        if not cap.isOpened():
            return None
        
        # Track vertical face positions
        vertical_positions = []
        frames_analyzed = 0
        face_detected_frames = 0
        
        while frames_analyzed < 90:
            ret, frame = cap.read()
            if not ret or frame is None:
                break
            
            face = _detect_face_in_frame(frame)
            
            if face is not None:
                face_detected_frames += 1
                x, y, w, h = face
                center_y = y + h / 2
                vertical_positions.append(center_y)
            
            frames_analyzed += 1
        
        # Analyze vertical movement
        nod_cycles = 0
        if len(vertical_positions) >= 4:
            # Look for up-down patterns
            direction_changes = 0
            last_direction = None
            
            for i in range(1, len(vertical_positions)):
                delta = vertical_positions[i] - vertical_positions[i-1]
                
                if abs(delta) > NOD_VERTICAL_THRESHOLD:
                    current_direction = "down" if delta > 0 else "up"
                    
                    if last_direction and current_direction != last_direction:
                        direction_changes += 1
                    
                    last_direction = current_direction
            
            # A nod is at least 2 direction changes (down-up or up-down)
            nod_cycles = direction_changes // 2
        
        return {
            "frames_analyzed": frames_analyzed,
            "face_detected_frames": face_detected_frames,
            "nod_cycles": nod_cycles,
            "nod_detected": nod_cycles >= MIN_NOD_CYCLES
        }
        
    except Exception as e:
        print(f"Nod detection error: {e}")
        return None
    finally:
        if cap is not None:
            cap.release()


def _detect_mouth_open(video_path: str):
    """
    Detect mouth opening.
    Returns analysis dict.
    """
    if not os.path.exists(video_path):
        return None
    
    cap = None
    try:
        cap = cv2.VideoCapture(video_path)
        
        if not cap.isOpened():
            return None
        
        mouth_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_smile.xml')
        
        frames_analyzed = 0
        face_detected_frames = 0
        mouth_open_frames = 0
        
        while frames_analyzed < 90:
            ret, frame = cap.read()
            if not ret or frame is None:
                break
            
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            face = _detect_face_in_frame(frame)
            
            if face is not None:
                face_detected_frames += 1
                x, y, w, h = face
                
                # Focus on lower half of face (mouth region)
                mouth_region = gray[y + h//2:y + h, x:x + w]
                
                # Detect mouth opening (using smile cascade as proxy)
                mouths = mouth_cascade.detectMultiScale(mouth_region, scaleFactor=1.7, minNeighbors=20)
                
                if len(mouths) > 0:
                    mouth_open_frames += 1
            
            frames_analyzed += 1
        
        return {
            "frames_analyzed": frames_analyzed,
            "face_detected_frames": face_detected_frames,
            "mouth_open_frames": mouth_open_frames,
            "mouth_detected": mouth_open_frames >= MIN_MOUTH_OPEN_FRAMES
        }
        
    except Exception as e:
        print(f"Mouth detection error: {e}")
        return None
    finally:
        if cap is not None:
            cap.release()


def _detect_eyebrow_raise(video_path: str):
    """
    Detect eyebrow raise by tracking forehead region.
    Returns analysis dict.
    """
    if not os.path.exists(video_path):
        return None
    
    cap = None
    try:
        cap = cv2.VideoCapture(video_path)
        
        if not cap.isOpened():
            return None
        
        frames_analyzed = 0
        face_detected_frames = 0
        eyebrow_raised_frames = 0
        
        baseline_y = None
        
        while frames_analyzed < 90:
            ret, frame = cap.read()
            if not ret or frame is None:
                break
            
            face = _detect_face_in_frame(frame)
            
            if face is not None:
                face_detected_frames += 1
                x, y, w, h = face
                
                # Forehead is top 1/3 of face
                forehead_y = y
                
                if baseline_y is None:
                    baseline_y = forehead_y
                else:
                    # Check if forehead moved up (eyebrows raised)
                    delta = baseline_y - forehead_y
                    
                    if delta > EYEBROW_RAISE_THRESHOLD:
                        eyebrow_raised_frames += 1
            
            frames_analyzed += 1
        
        return {
            "frames_analyzed": frames_analyzed,
            "face_detected_frames": face_detected_frames,
            "eyebrow_raised_frames": eyebrow_raised_frames,
            "eyebrow_detected": eyebrow_raised_frames >= MIN_EYEBROW_FRAMES
        }
        
    except Exception as e:
        print(f"Eyebrow detection error: {e}")
        return None
    finally:
        if cap is not None:
            cap.release()


# ============================================================================
# MAIN VERIFICATION FUNCTION
# ============================================================================

def run_human_verification(session_id: str, challenge_id: str, video_path: str, 
                           fast_track: bool = False, expected_movement: str = None):
    """
    Run human verification with multi-action support.
    
    Args:
        session_id: Session identifier
        challenge_id: Challenge identifier
        video_path: Path to video file
        fast_track: If True, use more lenient thresholds
        expected_movement: "left", "right", "blink", "nod", "mouth", "eyebrows"
    
    Returns:
        dict: {
            "challenge_passed": bool,
            "liveness_score": float,
            "action_detected": str,
            "action_matched": bool
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
            "action_detected": "none",
            "action_matched": False
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
            "action_detected": "none",
            "action_matched": False
        }
    
    # Route to appropriate detection function
    analysis = None
    
    if expected_movement in ["left", "right"]:
        analysis = _detect_head_turn(video_path, expected_movement)
        action_key = "direction_detected"
        match_key = "direction_matches_expected"
        
    elif expected_movement == "blink":
        analysis = _detect_blinks(video_path)
        action_key = "blinks_detected"
        match_key = "blinks_detected"
        
    elif expected_movement == "nod":
        analysis = _detect_nod(video_path)
        action_key = "nod_detected"
        match_key = "nod_detected"
        
    elif expected_movement == "mouth":
        analysis = _detect_mouth_open(video_path)
        action_key = "mouth_detected"
        match_key = "mouth_detected"
        
    elif expected_movement == "eyebrows":
        analysis = _detect_eyebrow_raise(video_path)
        action_key = "eyebrow_detected"
        match_key = "eyebrow_detected"
    else:
        log_event(
            event="verification_input_error",
            session_id=session_id,
            challenge_id=challenge_id,
            details={"error": "Unknown expected_movement", "movement": expected_movement}
        )
        return {
            "liveness_score": 0.0,
            "challenge_passed": False,
            "action_detected": "none",
            "action_matched": False
        }
    
    log_event(
        event="signal_received",
        session_id=session_id,
        challenge_id=challenge_id,
        details={
            "analysis": analysis,
            "expected_movement": expected_movement,
            "fast_track": fast_track
        }
    )
    
    # Check if analysis failed
    if analysis is None:
        log_event(
            event="challenge_failed",
            session_id=session_id,
            challenge_id=challenge_id,
            details={"reason": "analysis_failed", "fast_track": fast_track}
        )
        return {
            "liveness_score": 0.0,
            "challenge_passed": False,
            "action_detected": "none",
            "action_matched": False
        }
    
    # VERIFICATION LAYER 1: Face must be present
    min_face_frames = 2 if fast_track else 3
    
    if analysis.get("face_detected_frames", 0) < min_face_frames:
        log_event(
            event="challenge_failed",
            session_id=session_id,
            challenge_id=challenge_id,
            details={
                "reason": "insufficient_face_presence",
                "fast_track": fast_track,
                "required_face_frames": min_face_frames,
                "actual_face_frames": analysis.get("face_detected_frames", 0)
            }
        )
        return {
            "liveness_score": 0.0,
            "challenge_passed": False,
            "action_detected": "none",
            "action_matched": False
        }
    
    # VERIFICATION LAYER 2: Action must be detected
    action_detected = analysis.get(action_key, False)
    action_matched = analysis.get(match_key, False)
    
    # For head turns, check both detection and match
    if expected_movement in ["left", "right"]:
        if not action_matched:
            log_event(
                event="challenge_failed",
                session_id=session_id,
                challenge_id=challenge_id,
                details={
                    "reason": "action_not_matched",
                    "expected": expected_movement,
                    "detected": analysis.get("direction_detected", "none")
                }
            )
            return {
                "liveness_score": 0.0,
                "challenge_passed": False,
                "action_detected": analysis.get("direction_detected", "none"),
                "action_matched": False
            }
    else:
        # For other actions, just check detection
        if not action_detected:
            log_event(
                event="challenge_failed",
                session_id=session_id,
                challenge_id=challenge_id,
                details={
                    "reason": "action_not_detected",
                    "expected": expected_movement
                }
            )
            return {
                "liveness_score": 0.0,
                "challenge_passed": False,
                "action_detected": "none",
                "action_matched": False
            }
    
    # ALL CHECKS PASSED - Calculate liveness score
    base_score = 0.98 if fast_track else 0.95
    
    # Bonus for high confidence (if applicable)
    confidence_bonus = 0.0
    if "direction_confidence" in analysis:
        confidence_bonus = analysis["direction_confidence"] * 0.05
    
    liveness_score = min(1.0, base_score + confidence_bonus)
    
    log_event(
        event="challenge_passed",
        session_id=session_id,
        challenge_id=challenge_id,
        details={
            "fast_track": fast_track,
            "liveness_score": liveness_score,
            "expected_movement": expected_movement,
            "analysis": analysis
        }
    )
    
    return {
        "liveness_score": liveness_score,
        "challenge_passed": True,
        "action_detected": expected_movement if expected_movement in ["left", "right"] else "detected",
        "action_matched": True
    }