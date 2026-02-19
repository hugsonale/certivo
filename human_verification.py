import os
import cv2
import numpy as np
from logger import log_event
from typing import Optional, Dict, Any
import asyncio
from functools import lru_cache

# ============================================================================
# MEDIAPIPE — imported with graceful fallback to OpenCV-only mode
# ============================================================================

try:
    import mediapipe as mp
    _MP_FACE_MESH = mp.solutions.face_mesh
    MEDIAPIPE_AVAILABLE = True
    print("✅ MediaPipe available — using FaceMesh (468 landmarks)")
except ImportError:
    MEDIAPIPE_AVAILABLE = False
    _MP_FACE_MESH = None
    print("⚠️  MediaPipe not installed — falling back to OpenCV Haar Cascades")


# ============================================================================
# PHASE 3: MODEL CACHING - Shared instances across all requests
# ============================================================================

_CACHED_FACE_MESH = None
_CACHED_FACE_CASCADE = None
_CACHED_EYE_CASCADE = None
_CACHED_MOUTH_CASCADE = None


def _get_face_mesh():
    """
    Return cached FaceMesh instance (singleton pattern).
    Creates it once, reuses for all requests → saves ~500ms per verification.
    """
    global _CACHED_FACE_MESH
    
    if MEDIAPIPE_AVAILABLE:
        if _CACHED_FACE_MESH is None:
            print("🔧 Creating MediaPipe FaceMesh model (cached)")
            _CACHED_FACE_MESH = _MP_FACE_MESH.FaceMesh(
                static_image_mode=False,
                max_num_faces=1,
                refine_landmarks=True,
                min_detection_confidence=0.5,
                min_tracking_confidence=0.5,
            )
        return _CACHED_FACE_MESH
    return None


def _get_face_cascade():
    """Return cached OpenCV face cascade."""
    global _CACHED_FACE_CASCADE
    
    if _CACHED_FACE_CASCADE is None:
        _CACHED_FACE_CASCADE = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        )
    return _CACHED_FACE_CASCADE


def _get_eye_cascade():
    """Return cached OpenCV eye cascade."""
    global _CACHED_EYE_CASCADE
    
    if _CACHED_EYE_CASCADE is None:
        _CACHED_EYE_CASCADE = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_eye.xml"
        )
    return _CACHED_EYE_CASCADE


def _get_mouth_cascade():
    """Return cached OpenCV mouth cascade."""
    global _CACHED_MOUTH_CASCADE
    
    if _CACHED_MOUTH_CASCADE is None:
        _CACHED_MOUTH_CASCADE = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_smile.xml"
        )
    return _CACHED_MOUTH_CASCADE


# ============================================================================
# MEDIAPIPE LANDMARK INDICES
# ============================================================================

LEFT_EYE_IDX     = [33,  160, 158, 133, 153, 144]
RIGHT_EYE_IDX    = [362, 385, 387, 263, 373, 380]
MOUTH_TOP_IDX    = 13
MOUTH_BOTTOM_IDX = 14
MOUTH_LEFT_IDX   = 78
MOUTH_RIGHT_IDX  = 308
NOSE_TIP_IDX     = 1
LEFT_BROW_IDX    = [70, 63, 105, 66, 107]
RIGHT_BROW_IDX   = [300, 293, 334, 296, 336]
LEFT_EYE_TOP_IDX = 159
RIGHT_EYE_TOP_IDX = 386


# ============================================================================
# DETECTION THRESHOLDS
# ============================================================================

# Head turn
HEAD_TURN_MIN_DELTA   = 0.06
HEAD_TURN_EASY_DELTA  = 0.04

# Blink
EAR_CLOSED_THRESH     = 0.22
EAR_OPEN_THRESH       = 0.26
MIN_BLINK_FRAMES      = 2
MIN_BLINKS_REQUIRED   = 2

# Nod
NOD_MIN_DELTA         = 0.05
NOD_MIN_CYCLES        = 1
NOD_EASY_DELTA        = 0.03

# Mouth
MAR_OPEN_THRESH       = 0.45
MAR_EASY_THRESH       = 0.35
MIN_MOUTH_OPEN_FRAMES = 5

# Eyebrow
BROW_RAISE_THRESH     = 0.015
BROW_EASY_THRESH      = 0.008
MIN_BROW_RAISE_FRAMES = 5

# General
MIN_FACE_FRAMES       = 8
MIN_FACE_FRAMES_EASY  = 5
MAX_FRAMES_TO_ANALYSE = 150

# ============================================================================
# PHASE 2: FRAME SAMPLING - Speed up 2x by skipping frames
# ============================================================================

FRAME_SKIP = 2  # Process every 2nd frame (2x speed boost)


# ============================================================================
# UTILITY — Eye Aspect Ratio
# ============================================================================

def _ear(pts: np.ndarray) -> float:
    """Eye Aspect Ratio - lower value = more closed."""
    A = np.linalg.norm(pts[1] - pts[5])
    B = np.linalg.norm(pts[2] - pts[4])
    C = np.linalg.norm(pts[0] - pts[3]) + 1e-6
    return (A + B) / (2.0 * C)


# ============================================================================
# UTILITY — Mouth Aspect Ratio
# ============================================================================

def _mar(top: np.ndarray, bottom: np.ndarray,
         left: np.ndarray, right: np.ndarray) -> float:
    """Mouth Aspect Ratio - higher value = more open."""
    vertical   = np.linalg.norm(top - bottom)
    horizontal = np.linalg.norm(left - right) + 1e-6
    return vertical / horizontal


# ============================================================================
# PHASE 2: OPTIMIZED FRAME READING with early exit & sampling
# ============================================================================

def _read_frames_optimized(video_path: str, max_frames: int = MAX_FRAMES_TO_ANALYSE):
    """
    Read frames with intelligent sampling:
    - Skip every other frame (2x speed)
    - Stop early if we have enough data
    - Return list of BGR frames
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"❌ Cannot open video: {video_path}")
        return []

    frames = []
    frame_idx = 0
    
    while len(frames) < max_frames:
        ret, frame = cap.read()
        if not ret or frame is None:
            break
        
        # ✅ PHASE 2: Skip frames for 2x speed boost
        if frame_idx % FRAME_SKIP == 0:
            frames.append(frame)
        
        frame_idx += 1

    cap.release()
    print(f"📹 Read {len(frames)} frames from video (sampled from {frame_idx} total)")
    return frames


# ============================================================================
# PHASE 2: BETTER ERROR MESSAGES - User-friendly explanations
# ============================================================================

ERROR_MESSAGES = {
    "video_not_found": {
        "code": "VIDEO_NOT_FOUND",
        "user_message": "The video file could not be found. Please try recording again.",
        "tech_details": "Video file path does not exist or is inaccessible."
    },
    "video_too_short": {
        "code": "VIDEO_TOO_SHORT",
        "user_message": "Video recording was too short. Please hold still for at least 2 seconds.",
        "tech_details": "Video contained fewer than 10 frames."
    },
    "no_face_detected": {
        "code": "NO_FACE_DETECTED",
        "user_message": "We couldn't detect your face clearly. Please ensure good lighting and center your face in the frame.",
        "tech_details": "Face detection failed in sufficient number of frames."
    },
    "action_not_detected": {
        "code": "ACTION_NOT_DETECTED",
        "user_message": "We didn't detect the requested action. Please perform the action clearly and try again.",
        "tech_details": "Challenge-specific action detection failed validation criteria."
    },
    "direction_mismatch": {
        "code": "DIRECTION_MISMATCH",
        "user_message": "You moved in the wrong direction. Please follow the on-screen instruction carefully.",
        "tech_details": "Detected movement direction does not match expected direction."
    },
    "processing_error": {
        "code": "PROCESSING_ERROR",
        "user_message": "Something went wrong while processing your video. Please try again.",
        "tech_details": "Unexpected error during video analysis."
    }
}


def _build_error_response(error_type: str, details: str = None) -> Dict[str, Any]:
    """
    Build user-friendly error response with both user and technical messages.
    
    PHASE 2: Better error messages for debugging and UX.
    """
    error_info = ERROR_MESSAGES.get(error_type, ERROR_MESSAGES["processing_error"])
    
    return {
        "challenge_passed": False,
        "liveness_score": 0.0,
        "action_detected": "none",
        "action_matched": False,
        "direction_detected": "none",
        "direction_matched": False,
        "error": error_info["user_message"],
        "error_code": error_info["code"],
        "error_details": details or error_info["tech_details"],
    }


# ============================================================================
# DETECTOR 1 — Head Turn (left / right)
# ============================================================================

def detect_head_turn(video_path: str, expected_direction: str, fast_track: bool = False):
    """Detect head turn left or right using nose-tip X position tracking."""
    threshold = HEAD_TURN_EASY_DELTA if fast_track else HEAD_TURN_MIN_DELTA
    min_face  = MIN_FACE_FRAMES_EASY  if fast_track else MIN_FACE_FRAMES

    frames = _read_frames_optimized(video_path)
    if not frames:
        return _build_error_response("video_not_found")

    if len(frames) < 10:
        return _build_error_response("video_too_short", f"Only {len(frames)} frames")

    face_detected_frames = 0
    nose_x_positions = []

    if MEDIAPIPE_AVAILABLE:
        face_mesh = _get_face_mesh()
        for frame in frames:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            result = face_mesh.process(rgb)
            if result.multi_face_landmarks:
                face_detected_frames += 1
                lm = result.multi_face_landmarks[0].landmark
                nose_x_positions.append(lm[NOSE_TIP_IDX].x)

    else:
        cascade = _get_face_cascade()
        for frame in frames:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = cascade.detectMultiScale(gray, 1.1, 4, minSize=(40, 40))
            if len(faces) > 0:
                face_detected_frames += 1
                x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
                nose_x_positions.append((x + w / 2) / frame.shape[1])

    print(f"[HEAD TURN] face_frames={face_detected_frames}, positions={len(nose_x_positions)}")

    if face_detected_frames < min_face or len(nose_x_positions) < 4:
        return _build_error_response("no_face_detected", 
            f"Face visible in {face_detected_frames}/{len(frames)} frames, need {min_face}")

    # Calculate movement
    q = max(len(nose_x_positions) // 4, 1)
    start_x = float(np.mean(nose_x_positions[:q]))
    end_x   = float(np.mean(nose_x_positions[-q:]))
    delta   = end_x - start_x
    magnitude = abs(delta)

    print(f"[HEAD TURN] start={start_x:.3f} end={end_x:.3f} delta={delta:.3f} threshold={threshold:.3f}")

    if magnitude < threshold:
        return _build_error_response("action_not_detected",
            f"Head movement too small: {magnitude:.3f} < {threshold:.3f}")

    # Camera mirrored: delta > 0 = turned left, delta < 0 = turned right
    direction_detected = "left" if delta > 0 else "right"
    direction_matched  = (direction_detected == expected_direction)

    if not direction_matched:
        return _build_error_response("direction_mismatch",
            f"Expected {expected_direction}, detected {direction_detected}")

    print(f"[HEAD TURN] ✅ PASS - detected={direction_detected}")

    return {
        "passed": True,
        "face_detected_frames": face_detected_frames,
        "direction_detected": direction_detected,
        "direction_matched": True,
        "movement_magnitude": magnitude,
        "error": None,
    }


# ============================================================================
# DETECTOR 2 — Blink
# ============================================================================

def detect_blinks(video_path: str, fast_track: bool = False):
    """Detect blinks using Eye Aspect Ratio (EAR) with hysteresis."""
    min_face = MIN_FACE_FRAMES_EASY if fast_track else MIN_FACE_FRAMES

    frames = _read_frames_optimized(video_path)
    if not frames:
        return _build_error_response("video_not_found")

    if len(frames) < 10:
        return _build_error_response("video_too_short", f"Only {len(frames)} frames")

    face_detected_frames = 0
    blink_count   = 0
    eye_closed    = False
    closed_frames = 0

    if MEDIAPIPE_AVAILABLE:
        face_mesh = _get_face_mesh()
        for frame in frames:
            rgb    = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            result = face_mesh.process(rgb)

            if not result.multi_face_landmarks:
                continue

            face_detected_frames += 1
            lm = result.multi_face_landmarks[0].landmark
            h, w = frame.shape[:2]

            left_pts  = np.array([[lm[i].x * w, lm[i].y * h] for i in LEFT_EYE_IDX])
            right_pts = np.array([[lm[i].x * w, lm[i].y * h] for i in RIGHT_EYE_IDX])

            avg_ear = (_ear(left_pts) + _ear(right_pts)) / 2.0

            if avg_ear < EAR_CLOSED_THRESH:
                closed_frames += 1
                if closed_frames >= MIN_BLINK_FRAMES:
                    eye_closed = True
            else:
                if eye_closed and avg_ear > EAR_OPEN_THRESH:
                    blink_count += 1
                    print(f"[BLINK] blink #{blink_count} detected (EAR={avg_ear:.3f})")
                    eye_closed    = False
                    closed_frames = 0
                elif not eye_closed:
                    closed_frames = 0

    else:
        eye_cascade  = _get_eye_cascade()
        face_cascade = _get_face_cascade()

        for frame in frames:
            gray  = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = face_cascade.detectMultiScale(gray, 1.1, 4, minSize=(40, 40))
            if len(faces) == 0:
                continue
            face_detected_frames += 1
            x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
            roi = gray[y:y + h, x:x + w]
            eyes = eye_cascade.detectMultiScale(roi, 1.1, 5)

            if len(eyes) == 0:
                closed_frames += 1
                if closed_frames >= MIN_BLINK_FRAMES:
                    eye_closed = True
            else:
                if eye_closed:
                    blink_count += 1
                    eye_closed    = False
                    closed_frames = 0
                else:
                    closed_frames = 0

    if face_detected_frames < min_face:
        return _build_error_response("no_face_detected",
            f"Face visible in {face_detected_frames}/{len(frames)} frames")

    passed = blink_count >= MIN_BLINKS_REQUIRED
    print(f"[BLINK] face_frames={face_detected_frames} blinks={blink_count} passed={passed}")

    if not passed:
        return _build_error_response("action_not_detected",
            f"Only {blink_count} blink(s) detected, need {MIN_BLINKS_REQUIRED}")

    return {
        "passed": True,
        "face_detected_frames": face_detected_frames,
        "blink_count": blink_count,
        "error": None,
    }


# ============================================================================
# DETECTOR 3 — Nod
# ============================================================================

def detect_nod(video_path: str, fast_track: bool = False):
    """Detect head nod by tracking vertical nose-tip position."""
    threshold = NOD_EASY_DELTA  if fast_track else NOD_MIN_DELTA
    min_face  = MIN_FACE_FRAMES_EASY if fast_track else MIN_FACE_FRAMES

    frames = _read_frames_optimized(video_path)
    if not frames:
        return _build_error_response("video_not_found")

    if len(frames) < 10:
        return _build_error_response("video_too_short", f"Only {len(frames)} frames")

    face_detected_frames = 0
    nose_y_positions     = []

    if MEDIAPIPE_AVAILABLE:
        face_mesh = _get_face_mesh()
        for frame in frames:
            rgb    = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            result = face_mesh.process(rgb)
            if result.multi_face_landmarks:
                face_detected_frames += 1
                lm = result.multi_face_landmarks[0].landmark
                nose_y_positions.append(lm[NOSE_TIP_IDX].y)

    else:
        cascade = _get_face_cascade()
        for frame in frames:
            gray  = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = cascade.detectMultiScale(gray, 1.1, 4, minSize=(40, 40))
            if len(faces) > 0:
                face_detected_frames += 1
                x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
                nose_y_positions.append((y + h / 2) / frame.shape[0])

    print(f"[NOD] face_frames={face_detected_frames} y_positions={len(nose_y_positions)}")

    if face_detected_frames < min_face or len(nose_y_positions) < 6:
        return _build_error_response("no_face_detected",
            f"Face visible in {face_detected_frames}/{len(frames)} frames")

    # Smooth and count direction changes
    smoothed = np.convolve(nose_y_positions, np.ones(3) / 3, mode="valid")
    direction_changes = 0
    last_direction    = None

    for i in range(1, len(smoothed)):
        delta = smoothed[i] - smoothed[i - 1]
        if abs(delta) < 0.005:
            continue
        current_direction = "down" if delta > 0 else "up"
        if last_direction is not None and current_direction != last_direction:
            direction_changes += 1
        last_direction = current_direction

    nod_cycles = direction_changes // 2
    y_range = float(np.max(smoothed) - np.min(smoothed))
    passed  = nod_cycles >= NOD_MIN_CYCLES and y_range >= threshold

    print(f"[NOD] cycles={nod_cycles} range={y_range:.3f} passed={passed}")

    if not passed:
        return _build_error_response("action_not_detected",
            f"Nod not detected clearly (cycles={nod_cycles}, range={y_range:.3f})")

    return {
        "passed": True,
        "face_detected_frames": face_detected_frames,
        "nod_cycles": nod_cycles,
        "y_range": y_range,
        "error": None,
    }


# ============================================================================
# DETECTOR 4 — Mouth Open
# ============================================================================

def detect_mouth_open(video_path: str, fast_track: bool = False):
    """Detect open mouth using Mouth Aspect Ratio (MAR)."""
    mar_thresh = MAR_EASY_THRESH       if fast_track else MAR_OPEN_THRESH
    min_face   = MIN_FACE_FRAMES_EASY  if fast_track else MIN_FACE_FRAMES

    frames = _read_frames_optimized(video_path)
    if not frames:
        return _build_error_response("video_not_found")

    if len(frames) < 10:
        return _build_error_response("video_too_short", f"Only {len(frames)} frames")

    face_detected_frames = 0
    mouth_open_frames    = 0

    if MEDIAPIPE_AVAILABLE:
        face_mesh = _get_face_mesh()
        for frame in frames:
            rgb    = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            result = face_mesh.process(rgb)

            if not result.multi_face_landmarks:
                continue

            face_detected_frames += 1
            lm = result.multi_face_landmarks[0].landmark
            h, w = frame.shape[:2]

            top    = np.array([lm[MOUTH_TOP_IDX].x    * w, lm[MOUTH_TOP_IDX].y    * h])
            bottom = np.array([lm[MOUTH_BOTTOM_IDX].x * w, lm[MOUTH_BOTTOM_IDX].y * h])
            left   = np.array([lm[MOUTH_LEFT_IDX].x   * w, lm[MOUTH_LEFT_IDX].y   * h])
            right  = np.array([lm[MOUTH_RIGHT_IDX].x  * w, lm[MOUTH_RIGHT_IDX].y  * h])

            ratio = _mar(top, bottom, left, right)

            if ratio > mar_thresh:
                mouth_open_frames += 1

    else:
        face_cascade  = _get_face_cascade()
        mouth_cascade = _get_mouth_cascade()

        for frame in frames:
            gray  = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = face_cascade.detectMultiScale(gray, 1.1, 4, minSize=(40, 40))
            if len(faces) == 0:
                continue
            face_detected_frames += 1
            x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
            lower = gray[y + h // 2: y + h, x: x + w]
            mouths = mouth_cascade.detectMultiScale(lower, 1.7, 11)
            if len(mouths) > 0:
                mouth_open_frames += 1

    if face_detected_frames < min_face:
        return _build_error_response("no_face_detected",
            f"Face visible in {face_detected_frames}/{len(frames)} frames")

    passed = mouth_open_frames >= MIN_MOUTH_OPEN_FRAMES
    print(f"[MOUTH] face_frames={face_detected_frames} open_frames={mouth_open_frames} passed={passed}")

    if not passed:
        return _build_error_response("action_not_detected",
            f"Mouth open only in {mouth_open_frames} frame(s), need {MIN_MOUTH_OPEN_FRAMES}")

    return {
        "passed": True,
        "face_detected_frames": face_detected_frames,
        "mouth_open_frames": mouth_open_frames,
        "error": None,
    }


# ============================================================================
# DETECTOR 5 — Eyebrow Raise
# ============================================================================

def detect_eyebrow_raise(video_path: str, fast_track: bool = False):
    """Detect eyebrow raise by comparing eyebrow-to-eye-top distance."""
    raise_thresh = BROW_EASY_THRESH    if fast_track else BROW_RAISE_THRESH
    min_face     = MIN_FACE_FRAMES_EASY if fast_track else MIN_FACE_FRAMES

    frames = _read_frames_optimized(video_path)
    if not frames:
        return _build_error_response("video_not_found")

    if len(frames) < 10:
        return _build_error_response("video_too_short", f"Only {len(frames)} frames")

    face_detected_frames = 0
    brow_ratios          = []
    eyebrow_raise_frames = 0

    if MEDIAPIPE_AVAILABLE:
        face_mesh = _get_face_mesh()
        for frame in frames:
            rgb    = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            result = face_mesh.process(rgb)

            if not result.multi_face_landmarks:
                continue

            face_detected_frames += 1
            lm = result.multi_face_landmarks[0].landmark

            left_brow_y  = np.mean([lm[i].y for i in LEFT_BROW_IDX])
            right_brow_y = np.mean([lm[i].y for i in RIGHT_BROW_IDX])
            avg_brow_y   = (left_brow_y + right_brow_y) / 2.0

            left_eye_y   = lm[LEFT_EYE_TOP_IDX].y
            right_eye_y  = lm[RIGHT_EYE_TOP_IDX].y
            avg_eye_y    = (left_eye_y + right_eye_y) / 2.0

            brow_eye_dist = avg_eye_y - avg_brow_y
            brow_ratios.append(brow_eye_dist)

        if len(brow_ratios) >= 5:
            baseline_n  = max(len(brow_ratios) // 5, 3)
            baseline    = float(np.mean(brow_ratios[:baseline_n]))

            for ratio in brow_ratios:
                if (ratio - baseline) > raise_thresh:
                    eyebrow_raise_frames += 1

    else:
        face_cascade = _get_face_cascade()
        brightness_vals = []

        for frame in frames:
            gray  = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = face_cascade.detectMultiScale(gray, 1.1, 4, minSize=(40, 40))
            if len(faces) == 0:
                continue
            face_detected_frames += 1
            x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
            forehead = gray[y: y + h // 4, x: x + w]
            brightness_vals.append(float(forehead.mean()))

        if len(brightness_vals) >= 5:
            baseline  = float(np.mean(brightness_vals[:3]))
            for val in brightness_vals:
                if abs(val - baseline) > 3.0:
                    eyebrow_raise_frames += 1

    if face_detected_frames < min_face:
        return _build_error_response("no_face_detected",
            f"Face visible in {face_detected_frames}/{len(frames)} frames")

    passed = eyebrow_raise_frames >= MIN_BROW_RAISE_FRAMES

    print(f"[EYEBROW] face_frames={face_detected_frames} raise_frames={eyebrow_raise_frames} passed={passed}")

    if not passed:
        return _build_error_response("action_not_detected",
            f"Eyebrow raise detected in only {eyebrow_raise_frames} frame(s), need {MIN_BROW_RAISE_FRAMES}")

    return {
        "passed": True,
        "face_detected_frames": face_detected_frames,
        "eyebrow_raise_frames": eyebrow_raise_frames,
        "error": None,
    }


# ============================================================================
# ROUTER
# ============================================================================

def _run_detector(expected_movement: str, video_path: str, fast_track: bool):
    """Route to correct detection function."""
    m = expected_movement.lower().strip()

    if m == "left":
        return detect_head_turn(video_path, "left",  fast_track)
    elif m == "right":
        return detect_head_turn(video_path, "right", fast_track)
    elif m == "blink":
        return detect_blinks(video_path, fast_track)
    elif m == "nod":
        return detect_nod(video_path, fast_track)
    elif m == "mouth":
        return detect_mouth_open(video_path, fast_track)
    elif m == "eyebrows":
        return detect_eyebrow_raise(video_path, fast_track)
    else:
        return _build_error_response("processing_error", f"Unknown challenge type: {expected_movement}")


# ============================================================================
# PUBLIC ENTRY POINT
# ============================================================================

def run_human_verification(
    session_id: str,
    challenge_id: str,
    video_path: str,
    fast_track: bool = False,
    expected_movement: str = None,
    expected_direction: str = None,
):
    """
    Run human verification for any supported challenge type.
    
    PHASE 2 & 3 IMPROVEMENTS:
    - Model caching (reuse instances)
    - Frame sampling (2x speed)
    - Better error messages (user-friendly + tech details)
    """

    movement = (expected_movement or expected_direction or "").lower().strip()

    print(f"\n{'=' * 60}")
    print(f"🎯 VERIFICATION  session={session_id}  challenge={challenge_id}")
    print(f"   movement={movement}  fast_track={fast_track}")
    print(f"{'=' * 60}\n")

    VALID_MOVEMENTS = {"left", "right", "blink", "nod", "mouth", "eyebrows"}

    if not session_id or not challenge_id:
        return _build_error_response("processing_error", "Missing session_id or challenge_id")

    if not movement or movement not in VALID_MOVEMENTS:
        return _build_error_response("processing_error", f"Unknown challenge type: '{movement}'")

    if not video_path or not os.path.exists(video_path):
        return _build_error_response("video_not_found", f"Path: {video_path}")

    # Run detector
    try:
        detection = _run_detector(movement, video_path, fast_track)
    except Exception as exc:
        import traceback
        traceback.print_exc()
        log_event(
            event="detection_exception",
            session_id=session_id,
            challenge_id=challenge_id,
            details={"error": str(exc), "movement": movement},
        )
        return _build_error_response("processing_error", str(exc))

    # Check if detection itself returned an error
    if "error_code" in detection:
        log_event(
            event="challenge_failed",
            session_id=session_id,
            challenge_id=challenge_id,
            details={"movement": movement, "detection": detection},
        )
        return detection

    # Check if challenge passed
    challenge_passed = bool(detection.get("passed", False))

    if not challenge_passed:
        log_event(
            event="challenge_failed",
            session_id=session_id,
            challenge_id=challenge_id,
            details={"movement": movement, "detection": detection},
        )
        return _build_error_response("action_not_detected", detection.get("error", "Unknown"))

    # SUCCESS
    liveness_score = 0.98 if fast_track else 0.96

    if movement in ("left", "right"):
        mag = float(detection.get("movement_magnitude", 0))
        liveness_score = min(1.0, liveness_score + mag * 0.05)

    direction_detected = detection.get("direction_detected", movement)
    direction_matched  = detection.get("direction_matched", True)

    print(f"✅ PASS  liveness={liveness_score:.3f}  movement={movement}")

    log_event(
        event="challenge_passed",
        session_id=session_id,
        challenge_id=challenge_id,
        details={
            "movement": movement,
            "liveness_score": liveness_score,
            "fast_track": fast_track,
            "detection": detection,
        },
    )

    return {
        "challenge_passed":  True,
        "liveness_score":    liveness_score,
        "action_detected":   movement,
        "action_matched":    True,
        "direction_detected": direction_detected,
        "direction_matched":  direction_matched,
        "error":             None,
        "error_code":        None,
    }