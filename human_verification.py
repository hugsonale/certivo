import os
import cv2
import numpy as np
from logger import log_event

# ============================================================================
# BALANCED THRESHOLDS - Strict enough to catch no movement, lenient enough for real humans
# ============================================================================

MIN_VIDEO_FRAMES = 5  # Need at least 5 frames with motion
MOTION_THRESHOLD = 0.15  # Moderate sensitivity

# Direction detection
DIRECTION_THRESHOLD = 8  # 8 pixels minimum movement
DIRECTION_CONFIDENCE_FRAMES = 2  # Must see direction for 2+ frames

# Fast-track
FAST_TRACK_MIN_FRAMES = 3
FAST_TRACK_MOTION_THRESHOLD = 0.1


def _detect_face_in_frame(frame):
    """Detect face using Haar Cascade with optimized parameters"""
    try:
        face_cascade_path = cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
        face_cascade = cv2.CascadeClassifier(face_cascade_path)
        
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        
        # Single, optimized detection pass
        faces = face_cascade.detectMultiScale(
            gray, 
            scaleFactor=1.1, 
            minNeighbors=4, 
            minSize=(40, 40)
        )
        
        if len(faces) > 0:
            largest_face = max(faces, key=lambda f: f[2] * f[3])
            return largest_face
        
        return None
        
    except Exception as e:
        print(f"Face detection error: {e}")
        return None


def _detect_head_turn(video_path: str, expected_direction: str = None):
    """
    BALANCED head turn detection.
    - Requires REAL movement
    - Fast processing
    - Accurate direction detection
    """
    if not os.path.exists(video_path):
        print(f"❌ Video not found: {video_path}")
        return None
    
    cap = None
    try:
        cap = cv2.VideoCapture(video_path)
        
        if not cap.isOpened():
            print(f"❌ Cannot open video")
            return None
        
        # Get video FPS for accurate timing
        fps = cap.get(cv2.CAP_PROP_FPS)
        if fps == 0:
            fps = 30  # Default assumption
        
        print(f"📹 Video FPS: {fps}")
        
        # Read first frame
        ret, first_frame = cap.read()
        if not ret or first_frame is None:
            print("❌ Cannot read first frame")
            return None
        
        frame_height, frame_width = first_frame.shape[:2]
        
        face_positions = []
        prev_gray = cv2.cvtColor(first_frame, cv2.COLOR_BGR2GRAY)
        
        # Detect initial face
        initial_face = _detect_face_in_frame(first_frame)
        if initial_face is not None:
            x, y, w, h = initial_face
            face_positions.append({
                'frame': 0,
                'center_x': x + w / 2,
                'center_y': y + h / 2
            })
        
        frames_analyzed = 1
        total_motion = 0
        face_detected_frames = 1 if initial_face is not None else 0
        
        # Analyze up to 90 frames (~3 seconds at 30fps)
        max_frames = min(90, int(fps * 4))  # Max 4 seconds
        
        while frames_analyzed < max_frames:
            ret, frame = cap.read()
            if not ret or frame is None:
                break
            
            # Motion detection
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            diff = cv2.absdiff(prev_gray, gray)
            motion_score = diff.mean()
            
            if motion_score > MOTION_THRESHOLD:
                total_motion += 1
            
            # Face tracking
            face = _detect_face_in_frame(frame)
            
            if face is not None:
                face_detected_frames += 1
                x, y, w, h = face
                
                face_positions.append({
                    'frame': frames_analyzed,
                    'center_x': x + w / 2,
                    'center_y': y + h / 2
                })
            
            prev_gray = gray
            frames_analyzed += 1
        
        print(f"📊 Analyzed: {frames_analyzed} frames, {face_detected_frames} with face, {total_motion} motion")
        
        # ====================================================================
        # DIRECTION ANALYSIS
        # ====================================================================
        
        direction_detected = "none"
        direction_confidence = 0.0
        movement_magnitude = 0.0
        
        if len(face_positions) >= 3:
            # Calculate movements
            movements = []
            
            for i in range(1, len(face_positions)):
                delta_x = face_positions[i]['center_x'] - face_positions[i-1]['center_x']
                movements.append(delta_x)
            
            if movements:
                net_movement = sum(movements)
                movement_magnitude = abs(net_movement)
                
                # Count directional movements
                left_moves = sum(1 for m in movements if m < -DIRECTION_THRESHOLD)
                right_moves = sum(1 for m in movements if m > DIRECTION_THRESHOLD)
                
                print(f"📏 Net movement: {net_movement:.1f}px, Left: {left_moves}, Right: {right_moves}")
                
                # Determine direction (swap for camera mirroring)
                if movement_magnitude > DIRECTION_THRESHOLD:
                    if left_moves >= DIRECTION_CONFIDENCE_FRAMES and left_moves > right_moves:
                        direction_detected = "right"  # Swapped
                        direction_confidence = min(left_moves / len(movements), 1.0)
                    elif right_moves >= DIRECTION_CONFIDENCE_FRAMES and right_moves > left_moves:
                        direction_detected = "left"  # Swapped
                        direction_confidence = min(right_moves / len(movements), 1.0)
        
        # Check match
        direction_matches_expected = False
        if expected_direction:
            direction_matches_expected = (direction_detected == expected_direction.lower())
        
        print(f"✅ Direction: {direction_detected}, Expected: {expected_direction}, Match: {direction_matches_expected}")
        
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
        print(f"❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return None
    finally:
        if cap is not None:
            cap.release()


def run_human_verification(session_id: str, challenge_id: str, video_path: str, 
                           fast_track: bool = False, expected_direction: str = None):
    """
    BALANCED verification - catches no movement, passes real humans.
    FAST processing - under 2 seconds.
    """
    
    print(f"\n🎯 VERIFICATION: {expected_direction}")
    
    # Validate inputs
    if not session_id or not challenge_id:
        return {
            "liveness_score": 0.0,
            "challenge_passed": False,
            "direction_detected": "none",
            "direction_matched": False,
            "error": "Missing parameters"
        }
    
    if not video_path or not os.path.exists(video_path):
        return {
            "liveness_score": 0.0,
            "challenge_passed": False,
            "direction_detected": "none",
            "direction_matched": False,
            "error": "Video not found"
        }
    
    # Run detection
    analysis = _detect_head_turn(video_path, expected_direction)
    
    if analysis is None:
        return {
            "liveness_score": 0.0,
            "challenge_passed": False,
            "direction_detected": "none",
            "direction_matched": False,
            "error": "Analysis failed"
        }
    
    # ========================================================================
    # CHECK 1: Sufficient motion (STRICT - must have real movement)
    # ========================================================================
    
    min_motion = FAST_TRACK_MIN_FRAMES if fast_track else MIN_VIDEO_FRAMES
    
    if analysis.get("total_motion", 0) < min_motion:
        print(f"❌ FAIL: No movement ({analysis.get('total_motion', 0)} < {min_motion})")
        return {
            "liveness_score": 0.0,
            "challenge_passed": False,
            "direction_detected": "none",
            "direction_matched": False,
            "error": "No movement detected"
        }
    
    # ========================================================================
    # CHECK 2: Face must be visible
    # ========================================================================
    
    min_face = 2 if fast_track else 3
    
    if analysis.get("face_detected_frames", 0) < min_face:
        print(f"❌ FAIL: No face detected")
        return {
            "liveness_score": 0.0,
            "challenge_passed": False,
            "direction_detected": "none",
            "direction_matched": False,
            "error": "Face not detected"
        }
    
    # ========================================================================
    # CHECK 3: Direction must match (STRICT)
    # ========================================================================
    
    if expected_direction:
        direction_matched = analysis.get("direction_matches_expected", False)
        direction_detected = analysis.get("direction_detected", "none")
        
        if not direction_matched:
            print(f"❌ FAIL: Wrong direction (expected {expected_direction}, got {direction_detected})")
            return {
                "liveness_score": 0.0,
                "challenge_passed": False,
                "direction_detected": direction_detected,
                "direction_matched": False,
                "error": f"Wrong direction: expected {expected_direction}, detected {direction_detected}"
            }
    
    # ========================================================================
    # SUCCESS
    # ========================================================================
    
    base_score = 0.97 if fast_track else 0.95
    confidence_bonus = analysis.get("direction_confidence", 0.5) * 0.05
    liveness_score = min(1.0, base_score + confidence_bonus)
    
    print(f"✅ PASS! Score: {liveness_score:.2f}")
    
    log_event(
        event="challenge_passed",
        session_id=session_id,
        challenge_id=challenge_id,
        details={
            "liveness_score": liveness_score,
            "direction_detected": analysis["direction_detected"],
            "direction_matched": True
        }
    )
    
    return {
        "liveness_score": liveness_score,
        "challenge_passed": True,
        "direction_detected": analysis["direction_detected"],
        "direction_matched": True
    }