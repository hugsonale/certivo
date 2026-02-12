import os
import cv2
import numpy as np
from logger import log_event
import mediapipe as mp

# ============================================================================
# INITIALIZE MEDIAPIPE
# ============================================================================

mp_face_mesh = mp.solutions.face_mesh
mp_face_detection = mp.solutions.face_detection

# ============================================================================
# PRODUCTION THRESHOLDS (Balanced - Not too strict, not too lenient)
# ============================================================================

# Core thresholds
MIN_VIDEO_FRAMES = 30  # At least 1 second of video at 30fps
MIN_FACE_FRAMES = 20   # Face must be visible in at least 20 frames

# Head turn thresholds
HEAD_TURN_THRESHOLD = 0.15  # 15% movement across frame width
MIN_TURN_FRAMES = 5  # Must detect turn for at least 5 frames

# Blink thresholds
MIN_BLINKS = 2
MAX_BLINKS = 5
EYE_ASPECT_RATIO_THRESHOLD = 0.2  # Eyes closed when below this
MIN_BLINK_FRAMES = 2  # Blink must last at least 2 frames

# Nod thresholds
NOD_THRESHOLD = 0.08  # 8% vertical movement
MIN_NOD_CYCLES = 1  # At least 1 complete up-down cycle

# Mouth open thresholds
MOUTH_ASPECT_RATIO_THRESHOLD = 0.5  # Mouth open when above this
MIN_MOUTH_OPEN_FRAMES = 8  # Must be open for at least 8 frames

# Eyebrow raise thresholds
EYEBROW_RAISE_THRESHOLD = 0.03  # 3% upward movement
MIN_EYEBROW_FRAMES = 8


# ============================================================================
# MEDIAPIPE LANDMARK INDICES
# ============================================================================

# Eye landmarks (for blink detection)
LEFT_EYE = [33, 160, 158, 133, 153, 144]
RIGHT_EYE = [362, 385, 387, 263, 373, 380]

# Mouth landmarks (for mouth open detection)
MOUTH_TOP = 13
MOUTH_BOTTOM = 14
MOUTH_LEFT = 78
MOUTH_RIGHT = 308

# Eyebrow landmarks
LEFT_EYEBROW = [70, 63, 105, 66, 107]
RIGHT_EYEBROW = [300, 293, 334, 296, 336]


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def calculate_ear(eye_landmarks):
    """
    Calculate Eye Aspect Ratio (EAR) for blink detection.
    Lower EAR = eyes more closed.
    """
    # Vertical distances
    A = np.linalg.norm(eye_landmarks[1] - eye_landmarks[5])
    B = np.linalg.norm(eye_landmarks[2] - eye_landmarks[4])
    
    # Horizontal distance
    C = np.linalg.norm(eye_landmarks[0] - eye_landmarks[3])
    
    # EAR formula
    ear = (A + B) / (2.0 * C + 1e-6)  # Add epsilon to avoid division by zero
    return ear


def calculate_mar(mouth_landmarks):
    """
    Calculate Mouth Aspect Ratio (MAR) for mouth open detection.
    Higher MAR = mouth more open.
    """
    # Vertical distance
    vertical = np.linalg.norm(mouth_landmarks[0] - mouth_landmarks[1])
    
    # Horizontal distance
    horizontal = np.linalg.norm(mouth_landmarks[2] - mouth_landmarks[3])
    
    # MAR formula
    mar = vertical / (horizontal + 1e-6)
    return mar


# ============================================================================
# CHALLENGE-SPECIFIC DETECTION FUNCTIONS
# ============================================================================

def detect_head_turn(video_path: str, expected_direction: str):
    """
    Detect head turn left or right using MediaPipe Face Mesh.
    More reliable than Haar Cascades.
    
    Returns:
        dict: Analysis results with detection confidence
    """
    if not os.path.exists(video_path):
        print(f"❌ Video file not found: {video_path}")
        return None
    
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"❌ Cannot open video: {video_path}")
        return None
    
    face_mesh = mp_face_mesh.FaceMesh(
        static_image_mode=False,
        max_num_faces=1,
        refine_landmarks=True,
        min_detection_confidence=0.5,
        min_tracking_confidence=0.5
    )
    
    frames_analyzed = 0
    face_detected_frames = 0
    horizontal_positions = []
    frame_width = None
    
    print(f"🎥 Analyzing video for {expected_direction} turn...")
    
    while frames_analyzed < 150:  # Max ~5 seconds at 30fps
        ret, frame = cap.read()
        if not ret:
            break
        
        if frame_width is None:
            frame_width = frame.shape[1]
        
        # Convert to RGB for MediaPipe
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = face_mesh.process(rgb_frame)
        
        if results.multi_face_landmarks:
            face_detected_frames += 1
            landmarks = results.multi_face_landmarks[0]
            
            # Get nose tip position (landmark 1) - central reference point
            nose_x = landmarks.landmark[1].x
            horizontal_positions.append(nose_x)
        
        frames_analyzed += 1
    
    cap.release()
    face_mesh.close()
    
    print(f"📊 Analyzed {frames_analyzed} frames, face detected in {face_detected_frames}")
    
    # Analysis
    if len(horizontal_positions) < MIN_TURN_FRAMES:
        print(f"❌ Insufficient face tracking: {len(horizontal_positions)} positions")
        return {
            "frames_analyzed": frames_analyzed,
            "face_detected_frames": face_detected_frames,
            "direction_detected": "none",
            "direction_confidence": 0.0,
            "direction_matched": False
        }
    
    # Calculate movement
    start_pos = np.mean(horizontal_positions[:5])  # Average of first 5 frames
    end_pos = np.mean(horizontal_positions[-5:])   # Average of last 5 frames
    
    movement = end_pos - start_pos  # Positive = moved right, Negative = moved left
    movement_magnitude = abs(movement)
    
    print(f"📏 Movement: {movement:.4f} ({movement_magnitude:.4f} magnitude)")
    
    # Determine direction (account for camera mirroring)
    direction_detected = "none"
    direction_confidence = 0.0
    
    if movement_magnitude > HEAD_TURN_THRESHOLD:
        # Count frames moving in consistent direction
        movements = []
        for i in range(1, len(horizontal_positions)):
            delta = horizontal_positions[i] - horizontal_positions[i-1]
            movements.append(delta)
        
        left_moves = sum(1 for m in movements if m < -0.01)
        right_moves = sum(1 for m in movements if m > 0.01)
        
        # Camera is mirrored, so swap directions
        if movement < 0 and left_moves > right_moves:
            direction_detected = "right"  # User moved left, camera saw right
            direction_confidence = min(movement_magnitude / HEAD_TURN_THRESHOLD, 1.0)
        elif movement > 0 and right_moves > left_moves:
            direction_detected = "left"  # User moved right, camera saw left
            direction_confidence = min(movement_magnitude / HEAD_TURN_THRESHOLD, 1.0)
    
    direction_matched = (direction_detected == expected_direction)
    
    print(f"✅ Detected: {direction_detected}, Expected: {expected_direction}, Match: {direction_matched}")
    
    return {
        "frames_analyzed": frames_analyzed,
        "face_detected_frames": face_detected_frames,
        "direction_detected": direction_detected,
        "direction_confidence": direction_confidence,
        "direction_matched": direction_matched,
        "movement_magnitude": movement_magnitude
    }


def detect_blinks(video_path: str):
    """
    Detect blink count using MediaPipe Face Mesh Eye Aspect Ratio.
    Much more accurate than Haar Cascades.
    
    Returns:
        dict: Analysis results with blink count
    """
    if not os.path.exists(video_path):
        return None
    
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return None
    
    face_mesh = mp_face_mesh.FaceMesh(
        static_image_mode=False,
        max_num_faces=1,
        refine_landmarks=True,
        min_detection_confidence=0.5
    )
    
    frames_analyzed = 0
    face_detected_frames = 0
    blink_count = 0
    ear_history = []
    eyes_closed = False
    
    print(f"👁️ Analyzing video for blinks...")
    
    while frames_analyzed < 150:
        ret, frame = cap.read()
        if not ret:
            break
        
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = face_mesh.process(rgb_frame)
        
        if results.multi_face_landmarks:
            face_detected_frames += 1
            landmarks = results.multi_face_landmarks[0].landmark
            
            # Extract eye landmarks
            left_eye = np.array([(landmarks[i].x, landmarks[i].y) for i in LEFT_EYE])
            right_eye = np.array([(landmarks[i].x, landmarks[i].y) for i in RIGHT_EYE])
            
            # Calculate EAR for both eyes
            left_ear = calculate_ear(left_eye)
            right_ear = calculate_ear(right_eye)
            avg_ear = (left_ear + right_ear) / 2.0
            
            ear_history.append(avg_ear)
            
            # Detect blink
            if avg_ear < EYE_ASPECT_RATIO_THRESHOLD:
                if not eyes_closed:
                    eyes_closed = True
            else:
                if eyes_closed:
                    # Blink complete (eyes reopened)
                    blink_count += 1
                    print(f"👁️ Blink #{blink_count} detected at frame {frames_analyzed}")
                    eyes_closed = False
        
        frames_analyzed += 1
    
    cap.release()
    face_mesh.close()
    
    blinks_valid = MIN_BLINKS <= blink_count <= MAX_BLINKS
    
    print(f"📊 Total blinks: {blink_count}, Valid: {blinks_valid}")
    
    return {
        "frames_analyzed": frames_analyzed,
        "face_detected_frames": face_detected_frames,
        "blink_count": blink_count,
        "blinks_detected": blinks_valid,
        "expected_blinks": f"{MIN_BLINKS}-{MAX_BLINKS}"
    }


def detect_nod(video_path: str):
    """
    Detect head nod (vertical movement) using MediaPipe Face Mesh.
    
    Returns:
        dict: Analysis results with nod detection
    """
    if not os.path.exists(video_path):
        return None
    
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return None
    
    face_mesh = mp_face_mesh.FaceMesh(
        static_image_mode=False,
        max_num_faces=1,
        refine_landmarks=True,
        min_detection_confidence=0.5
    )
    
    frames_analyzed = 0
    face_detected_frames = 0
    vertical_positions = []
    
    print(f"↕️ Analyzing video for nod...")
    
    while frames_analyzed < 150:
        ret, frame = cap.read()
        if not ret:
            break
        
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = face_mesh.process(rgb_frame)
        
        if results.multi_face_landmarks:
            face_detected_frames += 1
            landmarks = results.multi_face_landmarks[0]
            
            # Get nose tip vertical position
            nose_y = landmarks.landmark[1].y
            vertical_positions.append(nose_y)
        
        frames_analyzed += 1
    
    cap.release()
    face_mesh.close()
    
    # Analyze vertical movement for nod pattern
    nod_detected = False
    nod_cycles = 0
    
    if len(vertical_positions) > 10:
        # Look for down-up or up-down patterns
        direction_changes = []
        
        for i in range(5, len(vertical_positions) - 5):
            before = np.mean(vertical_positions[i-5:i])
            after = np.mean(vertical_positions[i:i+5])
            delta = after - before
            
            if abs(delta) > NOD_THRESHOLD:
                direction_changes.append(delta)
        
        # Count direction reversals (nod cycles)
        if len(direction_changes) >= 2:
            for i in range(1, len(direction_changes)):
                # Check if direction reversed (+ to - or - to +)
                if (direction_changes[i] * direction_changes[i-1]) < 0:
                    nod_cycles += 1
        
        nod_detected = nod_cycles >= MIN_NOD_CYCLES
    
    print(f"📊 Nod cycles detected: {nod_cycles}, Valid: {nod_detected}")
    
    return {
        "frames_analyzed": frames_analyzed,
        "face_detected_frames": face_detected_frames,
        "nod_cycles": nod_cycles,
        "nod_detected": nod_detected
    }


def detect_mouth_open(video_path: str):
    """
    Detect mouth opening using MediaPipe Face Mesh.
    
    Returns:
        dict: Analysis results with mouth detection
    """
    if not os.path.exists(video_path):
        return None
    
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return None
    
    face_mesh = mp_face_mesh.FaceMesh(
        static_image_mode=False,
        max_num_faces=1,
        refine_landmarks=True,
        min_detection_confidence=0.5
    )
    
    frames_analyzed = 0
    face_detected_frames = 0
    mouth_open_frames = 0
    
    print(f"😮 Analyzing video for mouth open...")
    
    while frames_analyzed < 150:
        ret, frame = cap.read()
        if not ret:
            break
        
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = face_mesh.process(rgb_frame)
        
        if results.multi_face_landmarks:
            face_detected_frames += 1
            landmarks = results.multi_face_landmarks[0].landmark
            
            # Extract mouth landmarks
            mouth_top = np.array([landmarks[MOUTH_TOP].x, landmarks[MOUTH_TOP].y])
            mouth_bottom = np.array([landmarks[MOUTH_BOTTOM].x, landmarks[MOUTH_BOTTOM].y])
            mouth_left = np.array([landmarks[MOUTH_LEFT].x, landmarks[MOUTH_LEFT].y])
            mouth_right = np.array([landmarks[MOUTH_RIGHT].x, landmarks[MOUTH_RIGHT].y])
            
            mouth_landmarks = np.array([mouth_top, mouth_bottom, mouth_left, mouth_right])
            
            # Calculate MAR
            mar = calculate_mar(mouth_landmarks)
            
            if mar > MOUTH_ASPECT_RATIO_THRESHOLD:
                mouth_open_frames += 1
        
        frames_analyzed += 1
    
    cap.release()
    face_mesh.close()
    
    mouth_detected = mouth_open_frames >= MIN_MOUTH_OPEN_FRAMES
    
    print(f"📊 Mouth open frames: {mouth_open_frames}/{frames_analyzed}, Valid: {mouth_detected}")
    
    return {
        "frames_analyzed": frames_analyzed,
        "face_detected_frames": face_detected_frames,
        "mouth_open_frames": mouth_open_frames,
        "mouth_detected": mouth_detected
    }


def detect_eyebrow_raise(video_path: str):
    """
    Detect eyebrow raise using MediaPipe Face Mesh.
    
    Returns:
        dict: Analysis results with eyebrow detection
    """
    if not os.path.exists(video_path):
        return None
    
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return None
    
    face_mesh = mp_face_mesh.FaceMesh(
        static_image_mode=False,
        max_num_faces=1,
        refine_landmarks=True,
        min_detection_confidence=0.5
    )
    
    frames_analyzed = 0
    face_detected_frames = 0
    eyebrow_positions = []
    
    print(f"🤨 Analyzing video for eyebrow raise...")
    
    while frames_analyzed < 150:
        ret, frame = cap.read()
        if not ret:
            break
        
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = face_mesh.process(rgb_frame)
        
        if results.multi_face_landmarks:
            face_detected_frames += 1
            landmarks = results.multi_face_landmarks[0].landmark
            
            # Get average eyebrow position
            left_brow_y = np.mean([landmarks[i].y for i in LEFT_EYEBROW])
            right_brow_y = np.mean([landmarks[i].y for i in RIGHT_EYEBROW])
            avg_brow_y = (left_brow_y + right_brow_y) / 2
            
            eyebrow_positions.append(avg_brow_y)
        
        frames_analyzed += 1
    
    cap.release()
    face_mesh.close()
    
    # Analyze eyebrow movement
    eyebrow_raised_frames = 0
    
    if len(eyebrow_positions) > 10:
        baseline = np.mean(eyebrow_positions[:10])  # First 10 frames as baseline
        
        for pos in eyebrow_positions[10:]:
            # Eyebrows raised = position moves UP (smaller y value)
            if (baseline - pos) > EYEBROW_RAISE_THRESHOLD:
                eyebrow_raised_frames += 1
    
    eyebrow_detected = eyebrow_raised_frames >= MIN_EYEBROW_FRAMES
    
    print(f"📊 Eyebrow raised frames: {eyebrow_raised_frames}, Valid: {eyebrow_detected}")
    
    return {
        "frames_analyzed": frames_analyzed,
        "face_detected_frames": face_detected_frames,
        "eyebrow_raised_frames": eyebrow_raised_frames,
        "eyebrow_detected": eyebrow_detected
    }


# ============================================================================
# MAIN VERIFICATION FUNCTION
# ============================================================================

def run_human_verification(session_id: str, challenge_id: str, video_path: str, 
                           fast_track: bool = False, expected_movement: str = None):
    """
    Run human verification with multi-action support using MediaPipe.
    
    Args:
        session_id: Session identifier
        challenge_id: Challenge identifier
        video_path: Path to video file
        fast_track: If True, use more lenient thresholds (not implemented yet)
        expected_movement: "left", "right", "blink", "nod", "mouth", "eyebrows"
    
    Returns:
        dict: {
            "challenge_passed": bool,
            "liveness_score": float,
            "action_detected": str,
            "action_matched": bool,
            "error": str (optional)
        }
    """
    
    # Validate inputs
    if not session_id or not challenge_id:
        return {
            "liveness_score": 0.0,
            "challenge_passed": False,
            "action_detected": "none",
            "action_matched": False,
            "error": "Missing session_id or challenge_id"
        }
    
    if not video_path or not os.path.exists(video_path):
        return {
            "liveness_score": 0.0,
            "challenge_passed": False,
            "action_detected": "none",
            "action_matched": False,
            "error": "Video file not found"
        }
    
    print(f"\n{'='*60}")
    print(f"🎯 CHALLENGE: {expected_movement}")
    print(f"{'='*60}\n")
    
    # Route to appropriate detection function
    analysis = None
    
    try:
        if expected_movement == "left":
            analysis = detect_head_turn(video_path, "left")
        elif expected_movement == "right":
            analysis = detect_head_turn(video_path, "right")
        elif expected_movement == "blink":
            analysis = detect_blinks(video_path)
        elif expected_movement == "nod":
            analysis = detect_nod(video_path)
        elif expected_movement == "mouth":
            analysis = detect_mouth_open(video_path)
        elif expected_movement == "eyebrows":
            analysis = detect_eyebrow_raise(video_path)
        else:
            return {
                "liveness_score": 0.0,
                "challenge_passed": False,
                "action_detected": "none",
                "action_matched": False,
                "error": f"Unknown challenge type: {expected_movement}"
            }
    
    except Exception as e:
        print(f"❌ Detection error: {e}")
        log_event(
            event="detection_error",
            session_id=session_id,
            challenge_id=challenge_id,
            details={"error": str(e), "expected_movement": expected_movement}
        )
        return {
            "liveness_score": 0.0,
            "challenge_passed": False,
            "action_detected": "none",
            "action_matched": False,
            "error": "Detection failed"
        }
    
    # Check if analysis failed
    if analysis is None:
        return {
            "liveness_score": 0.0,
            "challenge_passed": False,
            "action_detected": "none",
            "action_matched": False,
            "error": "Video analysis failed"
        }
    
    # Check minimum face presence
    if analysis.get("face_detected_frames", 0) < MIN_FACE_FRAMES:
        print(f"❌ Insufficient face presence: {analysis.get('face_detected_frames', 0)} < {MIN_FACE_FRAMES}")
        return {
            "liveness_score": 0.0,
            "challenge_passed": False,
            "action_detected": "none",
            "action_matched": False,
            "error": "Face not visible enough"
        }
    
    # Determine if challenge passed
    challenge_passed = False
    action_detected = "none"
    
    if expected_movement in ["left", "right"]:
        challenge_passed = analysis.get("direction_matched", False)
        action_detected = analysis.get("direction_detected", "none")
        
    elif expected_movement == "blink":
        challenge_passed = analysis.get("blinks_detected", False)
        action_detected = f"{analysis.get('blink_count', 0)} blinks"
        
    elif expected_movement == "nod":
        challenge_passed = analysis.get("nod_detected", False)
        action_detected = "nod" if challenge_passed else "none"
        
    elif expected_movement == "mouth":
        challenge_passed = analysis.get("mouth_detected", False)
        action_detected = "mouth_open" if challenge_passed else "none"
        
    elif expected_movement == "eyebrows":
        challenge_passed = analysis.get("eyebrow_detected", False)
        action_detected = "eyebrows_raised" if challenge_passed else "none"
    
    # Calculate liveness score
    if challenge_passed:
        base_score = 0.95
        
        # Bonus for high confidence (head turns)
        if "direction_confidence" in analysis:
            confidence_bonus = analysis["direction_confidence"] * 0.05
            liveness_score = min(1.0, base_score + confidence_bonus)
        else:
            liveness_score = base_score
    else:
        liveness_score = 0.0
    
    print(f"\n{'='*60}")
    print(f"{'✅ PASSED' if challenge_passed else '❌ FAILED'}")
    print(f"Score: {liveness_score:.2f}")
    print(f"{'='*60}\n")
    
    # Log result
    log_event(
        event="challenge_passed" if challenge_passed else "challenge_failed",
        session_id=session_id,
        challenge_id=challenge_id,
        details={
            "expected_movement": expected_movement,
            "challenge_passed": challenge_passed,
            "liveness_score": liveness_score,
            "analysis": analysis
        }
    )
    
    return {
        "liveness_score": liveness_score,
        "challenge_passed": challenge_passed,
        "action_detected": action_detected,
        "action_matched": challenge_passed,
        "direction_detected": analysis.get("direction_detected", "none"),
        "direction_matched": analysis.get("direction_matched", False)
    }