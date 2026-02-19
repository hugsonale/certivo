import os
import cv2
import numpy as np
from logger import log_event

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
# MEDIAPIPE LANDMARK INDICES
# ============================================================================

# Left eye  (6-point EAR formula)
LEFT_EYE_IDX  = [33,  160, 158, 133, 153, 144]
# Right eye (6-point EAR formula)
RIGHT_EYE_IDX = [362, 385, 387, 263, 373, 380]

# Mouth — inner lip
MOUTH_TOP_IDX    = 13
MOUTH_BOTTOM_IDX = 14
MOUTH_LEFT_IDX   = 78
MOUTH_RIGHT_IDX  = 308

# Nose tip  (used for head-turn & nod tracking)
NOSE_TIP_IDX = 1

# Eyebrows — middle landmark on each brow
LEFT_BROW_IDX  = [70, 63, 105, 66, 107]   # top of left brow
RIGHT_BROW_IDX = [300, 293, 334, 296, 336] # top of right brow

# Eye-centre landmark (for eyebrow-distance ratio)
LEFT_EYE_TOP_IDX  = 159   # top of left iris
RIGHT_EYE_TOP_IDX = 386   # top of right iris


# ============================================================================
# DETECTION THRESHOLDS
# ============================================================================

# ---- Head turn ----
HEAD_TURN_MIN_DELTA   = 0.06   # minimum normalised horizontal movement (6 % of frame)
HEAD_TURN_EASY_DELTA  = 0.04   # easy / fast-track threshold

# ---- Blink ----
EAR_CLOSED_THRESH     = 0.22   # EAR below this → eyes closed
EAR_OPEN_THRESH       = 0.26   # EAR above this → eyes open (hysteresis)
MIN_BLINK_FRAMES      = 2      # blink must last at least 2 frames
MIN_BLINKS_REQUIRED   = 2      # user must blink at least twice

# ---- Nod ----
NOD_MIN_DELTA         = 0.05   # minimum normalised vertical movement
NOD_MIN_CYCLES        = 1      # at least 1 complete down-up or up-down cycle
NOD_EASY_DELTA        = 0.03   # easy / fast-track threshold

# ---- Mouth open ----
MAR_OPEN_THRESH       = 0.45   # MAR above this → mouth open
MAR_EASY_THRESH       = 0.35   # easy / fast-track threshold
MIN_MOUTH_OPEN_FRAMES = 5      # must stay open for at least 5 frames

# ---- Eyebrow raise ----
BROW_RAISE_THRESH     = 0.015  # normalised upward movement of brow relative to eye
BROW_EASY_THRESH      = 0.008  # easy / fast-track threshold
MIN_BROW_RAISE_FRAMES = 5      # must stay raised for at least 5 frames

# ---- General ----
MIN_FACE_FRAMES       = 8      # face must be visible in at least 8 frames
MIN_FACE_FRAMES_EASY  = 5      # easy / fast-track
MAX_FRAMES_TO_ANALYSE = 150    # cap at ~5 seconds @ 30 fps


# ============================================================================
# UTILITY — Eye Aspect Ratio
# ============================================================================

def _ear(pts: np.ndarray) -> float:
    """
    Eye Aspect Ratio.
    pts shape: (6, 2)  —  [p1 … p6] following the standard 6-point model.
    Lower value → more closed.
    """
    A = np.linalg.norm(pts[1] - pts[5])
    B = np.linalg.norm(pts[2] - pts[4])
    C = np.linalg.norm(pts[0] - pts[3]) + 1e-6
    return (A + B) / (2.0 * C)


# ============================================================================
# UTILITY — Mouth Aspect Ratio
# ============================================================================

def _mar(top: np.ndarray, bottom: np.ndarray,
         left: np.ndarray, right: np.ndarray) -> float:
    """
    Mouth Aspect Ratio.
    Higher value → more open.
    """
    vertical   = np.linalg.norm(top - bottom)
    horizontal = np.linalg.norm(left - right) + 1e-6
    return vertical / horizontal


# ============================================================================
# UTILITY — build FaceMesh instance
# ============================================================================

def _make_face_mesh():
    return _MP_FACE_MESH.FaceMesh(
        static_image_mode=False,
        max_num_faces=1,
        refine_landmarks=True,
        min_detection_confidence=0.5,
        min_tracking_confidence=0.5,
    )


# ============================================================================
# UTILITY — read all frames from a video file
# ============================================================================

def _read_frames(video_path: str):
    """
    Read up to MAX_FRAMES_TO_ANALYSE BGR frames from video_path.
    Returns list of frames, or empty list on failure.
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"❌ Cannot open video: {video_path}")
        return []

    frames = []
    while len(frames) < MAX_FRAMES_TO_ANALYSE:
        ret, frame = cap.read()
        if not ret or frame is None:
            break
        frames.append(frame)

    cap.release()
    print(f"📹 Read {len(frames)} frames from video")
    return frames


# ============================================================================
# DETECTOR 1 — Head Turn  (left / right)
# ============================================================================

def detect_head_turn(video_path: str, expected_direction: str, fast_track: bool = False):
    """
    Detect head turn left or right using nose-tip X position tracking.

    Returns dict with keys:
        face_detected_frames, direction_detected, direction_matched,
        movement_magnitude, passed
    """
    threshold = HEAD_TURN_EASY_DELTA if fast_track else HEAD_TURN_MIN_DELTA
    min_face  = MIN_FACE_FRAMES_EASY  if fast_track else MIN_FACE_FRAMES

    frames = _read_frames(video_path)
    if not frames:
        return {"passed": False, "error": "Could not read video", "face_detected_frames": 0}

    face_detected_frames = 0
    nose_x_positions = []

    if MEDIAPIPE_AVAILABLE:
        face_mesh = _make_face_mesh()
        for frame in frames:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            result = face_mesh.process(rgb)
            if result.multi_face_landmarks:
                face_detected_frames += 1
                lm = result.multi_face_landmarks[0].landmark
                nose_x_positions.append(lm[NOSE_TIP_IDX].x)
        face_mesh.close()

    else:
        # OpenCV fallback
        cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        for frame in frames:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = cascade.detectMultiScale(gray, 1.1, 4, minSize=(40, 40))
            if len(faces) > 0:
                face_detected_frames += 1
                x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
                # Normalise to [0,1]
                nose_x_positions.append((x + w / 2) / frame.shape[1])

    print(f"[HEAD TURN] face_frames={face_detected_frames}, positions={len(nose_x_positions)}")

    if face_detected_frames < min_face or len(nose_x_positions) < 4:
        return {
            "passed": False,
            "error": "Face not visible enough",
            "face_detected_frames": face_detected_frames,
            "direction_detected": "none",
            "direction_matched": False,
        }

    # Use first-quarter average vs last-quarter average for robustness
    q = max(len(nose_x_positions) // 4, 1)
    start_x = float(np.mean(nose_x_positions[:q]))
    end_x   = float(np.mean(nose_x_positions[-q:]))
    delta   = end_x - start_x          # positive = moved right in frame
    magnitude = abs(delta)

    print(f"[HEAD TURN] start_x={start_x:.3f} end_x={end_x:.3f} delta={delta:.3f} threshold={threshold:.3f}")

    # Camera is mirrored: moving left in the real world → nose moves RIGHT in frame (+delta)
    # Moving right in the real world → nose moves LEFT in frame  (-delta)
    if magnitude < threshold:
        return {
            "passed": False,
            "error": "Head movement too small",
            "face_detected_frames": face_detected_frames,
            "direction_detected": "none",
            "direction_matched": False,
            "movement_magnitude": magnitude,
        }

    # delta > 0 (nose went right in frame) → user turned LEFT
    # delta < 0 (nose went left  in frame) → user turned RIGHT
    direction_detected = "left" if delta > 0 else "right"
    direction_matched  = (direction_detected == expected_direction)

    print(f"[HEAD TURN] detected={direction_detected} expected={expected_direction} matched={direction_matched}")

    return {
        "passed": direction_matched,
        "face_detected_frames": face_detected_frames,
        "direction_detected": direction_detected,
        "direction_matched": direction_matched,
        "movement_magnitude": magnitude,
        "error": None if direction_matched else f"Expected {expected_direction}, detected {direction_detected}",
    }


# ============================================================================
# DETECTOR 2 — Blink
# ============================================================================

def detect_blinks(video_path: str, fast_track: bool = False):
    """
    Detect blinks using Eye Aspect Ratio (EAR) with hysteresis.

    Returns dict with keys:
        face_detected_frames, blink_count, passed
    """
    min_face = MIN_FACE_FRAMES_EASY if fast_track else MIN_FACE_FRAMES

    frames = _read_frames(video_path)
    if not frames:
        return {"passed": False, "error": "Could not read video", "face_detected_frames": 0}

    face_detected_frames = 0
    blink_count   = 0
    eye_closed    = False
    closed_frames = 0

    if MEDIAPIPE_AVAILABLE:
        face_mesh = _make_face_mesh()
        for frame in frames:
            rgb    = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            result = face_mesh.process(rgb)

            if not result.multi_face_landmarks:
                continue

            face_detected_frames += 1
            lm = result.multi_face_landmarks[0].landmark
            h, w = frame.shape[:2]

            # Extract 2-D coordinates for each eye
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

        face_mesh.close()

    else:
        # OpenCV fallback — use eye cascade presence as proxy
        eye_cascade  = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_eye.xml")
        face_cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml")

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

    passed = blink_count >= MIN_BLINKS_REQUIRED
    print(f"[BLINK] face_frames={face_detected_frames} blinks={blink_count} passed={passed}")

    return {
        "passed": passed,
        "face_detected_frames": face_detected_frames,
        "blink_count": blink_count,
        "error": None if passed else f"Only {blink_count} blink(s) detected, need {MIN_BLINKS_REQUIRED}",
    }


# ============================================================================
# DETECTOR 3 — Nod  (up / down vertical movement)
# ============================================================================

def detect_nod(video_path: str, fast_track: bool = False):
    """
    Detect a head nod by tracking vertical nose-tip position.

    A complete nod = at least one direction reversal (down → up  or  up → down).

    Returns dict with keys:
        face_detected_frames, nod_cycles, passed
    """
    threshold = NOD_EASY_DELTA  if fast_track else NOD_MIN_DELTA
    min_face  = MIN_FACE_FRAMES_EASY if fast_track else MIN_FACE_FRAMES

    frames = _read_frames(video_path)
    if not frames:
        return {"passed": False, "error": "Could not read video", "face_detected_frames": 0}

    face_detected_frames = 0
    nose_y_positions     = []

    if MEDIAPIPE_AVAILABLE:
        face_mesh = _make_face_mesh()
        for frame in frames:
            rgb    = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            result = face_mesh.process(rgb)
            if result.multi_face_landmarks:
                face_detected_frames += 1
                lm = result.multi_face_landmarks[0].landmark
                nose_y_positions.append(lm[NOSE_TIP_IDX].y)
        face_mesh.close()

    else:
        cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        for frame in frames:
            gray  = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = cascade.detectMultiScale(gray, 1.1, 4, minSize=(40, 40))
            if len(faces) > 0:
                face_detected_frames += 1
                x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
                nose_y_positions.append((y + h / 2) / frame.shape[0])

    print(f"[NOD] face_frames={face_detected_frames} y_positions={len(nose_y_positions)}")

    if face_detected_frames < min_face or len(nose_y_positions) < 6:
        return {
            "passed": False,
            "error": "Face not visible enough",
            "face_detected_frames": face_detected_frames,
            "nod_cycles": 0,
        }

    # Smooth the position data with a 3-frame rolling average
    smoothed = np.convolve(nose_y_positions, np.ones(3) / 3, mode="valid")

    # Count direction changes that exceed the threshold
    direction_changes = 0
    last_direction    = None

    for i in range(1, len(smoothed)):
        delta = smoothed[i] - smoothed[i - 1]
        if abs(delta) < 0.005:          # ignore micro-jitter
            continue
        current_direction = "down" if delta > 0 else "up"
        if last_direction is not None and current_direction != last_direction:
            direction_changes += 1
        last_direction = current_direction

    # Each full nod = 2 direction changes (down + up)
    nod_cycles = direction_changes // 2

    # Also check overall vertical range as a sanity check
    y_range = float(np.max(smoothed) - np.min(smoothed))
    passed  = nod_cycles >= NOD_MIN_CYCLES and y_range >= threshold

    print(f"[NOD] direction_changes={direction_changes} nod_cycles={nod_cycles} y_range={y_range:.3f} passed={passed}")

    return {
        "passed": passed,
        "face_detected_frames": face_detected_frames,
        "nod_cycles": nod_cycles,
        "y_range": y_range,
        "error": None if passed else f"Nod not clearly detected (cycles={nod_cycles}, range={y_range:.3f})",
    }


# ============================================================================
# DETECTOR 4 — Mouth Open
# ============================================================================

def detect_mouth_open(video_path: str, fast_track: bool = False):
    """
    Detect open mouth using Mouth Aspect Ratio (MAR).

    Returns dict with keys:
        face_detected_frames, mouth_open_frames, passed
    """
    mar_thresh = MAR_EASY_THRESH       if fast_track else MAR_OPEN_THRESH
    min_face   = MIN_FACE_FRAMES_EASY  if fast_track else MIN_FACE_FRAMES

    frames = _read_frames(video_path)
    if not frames:
        return {"passed": False, "error": "Could not read video", "face_detected_frames": 0}

    face_detected_frames = 0
    mouth_open_frames    = 0

    if MEDIAPIPE_AVAILABLE:
        face_mesh = _make_face_mesh()
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

        face_mesh.close()

    else:
        # OpenCV fallback — use smile/mouth cascade
        face_cascade  = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        mouth_cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_smile.xml")

        for frame in frames:
            gray  = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = face_cascade.detectMultiScale(gray, 1.1, 4, minSize=(40, 40))
            if len(faces) == 0:
                continue
            face_detected_frames += 1
            x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
            # Focus on lower half of face
            lower = gray[y + h // 2: y + h, x: x + w]
            mouths = mouth_cascade.detectMultiScale(lower, 1.7, 11)
            if len(mouths) > 0:
                mouth_open_frames += 1

    passed = face_detected_frames >= min_face and mouth_open_frames >= MIN_MOUTH_OPEN_FRAMES
    print(f"[MOUTH] face_frames={face_detected_frames} open_frames={mouth_open_frames} passed={passed}")

    return {
        "passed": passed,
        "face_detected_frames": face_detected_frames,
        "mouth_open_frames": mouth_open_frames,
        "error": None if passed else f"Mouth open only in {mouth_open_frames} frame(s), need {MIN_MOUTH_OPEN_FRAMES}",
    }


# ============================================================================
# DETECTOR 5 — Eyebrow Raise
# ============================================================================

def detect_eyebrow_raise(video_path: str, fast_track: bool = False):
    """
    Detect eyebrow raise by comparing eyebrow-to-eye-top distance over time.

    Uses normalised ratio:  eyebrow_y_mean / eye_top_y  (MediaPipe coords, y increases downward)
    When eyebrows raise, eyebrow Y decreases faster than eye_top Y → ratio drops.

    Returns dict with keys:
        face_detected_frames, eyebrow_raise_frames, passed
    """
    raise_thresh = BROW_EASY_THRESH    if fast_track else BROW_RAISE_THRESH
    min_face     = MIN_FACE_FRAMES_EASY if fast_track else MIN_FACE_FRAMES

    frames = _read_frames(video_path)
    if not frames:
        return {"passed": False, "error": "Could not read video", "face_detected_frames": 0}

    face_detected_frames = 0
    brow_ratios          = []          # one value per frame
    eyebrow_raise_frames = 0

    if MEDIAPIPE_AVAILABLE:
        face_mesh = _make_face_mesh()
        for frame in frames:
            rgb    = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            result = face_mesh.process(rgb)

            if not result.multi_face_landmarks:
                continue

            face_detected_frames += 1
            lm = result.multi_face_landmarks[0].landmark

            # Average brow Y (top of brow arches)
            left_brow_y  = np.mean([lm[i].y for i in LEFT_BROW_IDX])
            right_brow_y = np.mean([lm[i].y for i in RIGHT_BROW_IDX])
            avg_brow_y   = (left_brow_y + right_brow_y) / 2.0

            # Eye-top Y reference
            left_eye_y   = lm[LEFT_EYE_TOP_IDX].y
            right_eye_y  = lm[RIGHT_EYE_TOP_IDX].y
            avg_eye_y    = (left_eye_y + right_eye_y) / 2.0

            # Distance between brow and eye top (in normalised coords)
            # Larger distance = more space = brows raised higher
            brow_eye_dist = avg_eye_y - avg_brow_y   # positive because brow is above eye
            brow_ratios.append(brow_eye_dist)

        face_mesh.close()

        if len(brow_ratios) >= 5:
            # Baseline = average of first 20% of frames
            baseline_n  = max(len(brow_ratios) // 5, 3)
            baseline    = float(np.mean(brow_ratios[:baseline_n]))

            for ratio in brow_ratios:
                # When eyebrows are raised, brow_eye_dist INCREASES
                if (ratio - baseline) > raise_thresh:
                    eyebrow_raise_frames += 1

            print(f"[EYEBROW] baseline={baseline:.4f} raise_thresh={raise_thresh:.4f}")

    else:
        # OpenCV fallback — very basic: track upper face brightness change
        # Not as accurate but provides a usable fallback
        face_cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        brightness_vals = []

        for frame in frames:
            gray  = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = face_cascade.detectMultiScale(gray, 1.1, 4, minSize=(40, 40))
            if len(faces) == 0:
                continue
            face_detected_frames += 1
            x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
            # Forehead region (top 25% of face)
            forehead = gray[y: y + h // 4, x: x + w]
            brightness_vals.append(float(forehead.mean()))

        if len(brightness_vals) >= 5:
            baseline  = float(np.mean(brightness_vals[:3]))
            for val in brightness_vals:
                if abs(val - baseline) > 3.0:   # 3-unit brightness change
                    eyebrow_raise_frames += 1

    passed = face_detected_frames >= min_face and eyebrow_raise_frames >= MIN_BROW_RAISE_FRAMES

    print(f"[EYEBROW] face_frames={face_detected_frames} raise_frames={eyebrow_raise_frames} passed={passed}")

    return {
        "passed": passed,
        "face_detected_frames": face_detected_frames,
        "eyebrow_raise_frames": eyebrow_raise_frames,
        "error": None if passed else f"Eyebrow raise detected in only {eyebrow_raise_frames} frame(s), need {MIN_BROW_RAISE_FRAMES}",
    }


# ============================================================================
# ROUTER — dispatch to correct detector
# ============================================================================

def _run_detector(expected_movement: str, video_path: str, fast_track: bool):
    """
    Route to the correct detection function based on expected_movement.
    Returns a result dict that always contains 'passed' and 'face_detected_frames'.
    """
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
        return {
            "passed": False,
            "face_detected_frames": 0,
            "error": f"Unknown challenge type: {expected_movement}",
        }


# ============================================================================
# PUBLIC ENTRY POINT
# ============================================================================

def run_human_verification(
    session_id: str,
    challenge_id: str,
    video_path: str,
    fast_track: bool = False,
    expected_movement: str = None,
    # Legacy parameter kept for backwards compatibility with main.py
    expected_direction: str = None,
):
    """
    Run human verification for any supported challenge type.

    Args:
        session_id        : str   - Session/device identifier for logging.
        challenge_id      : str   - Unique challenge ID.
        video_path        : str   - Path to uploaded .webm video.
        fast_track        : bool  - Trusted device → more lenient thresholds.
        expected_movement : str   - Challenge type: left|right|blink|nod|mouth|eyebrows
        expected_direction: str   - Legacy alias for expected_movement (left|right).

    Returns:
        dict with keys:
            challenge_passed  : bool
            liveness_score    : float  (0.0 – 1.0)
            action_detected   : str
            action_matched    : bool
            direction_detected: str    (legacy compat)
            direction_matched : bool   (legacy compat)
            error             : str | None
    """

    # ------------------------------------------------------------------ #
    # Normalise expected_movement                                         #
    # ------------------------------------------------------------------ #
    movement = (expected_movement or expected_direction or "").lower().strip()

    print(f"\n{'=' * 60}")
    print(f"🎯 VERIFICATION  session={session_id}  challenge={challenge_id}")
    print(f"   movement={movement}  fast_track={fast_track}")
    print(f"{'=' * 60}\n")

    # ------------------------------------------------------------------ #
    # Input validation                                                    #
    # ------------------------------------------------------------------ #
    VALID_MOVEMENTS = {"left", "right", "blink", "nod", "mouth", "eyebrows"}

    if not session_id or not challenge_id:
        return _fail_result("Missing session_id or challenge_id")

    if not movement or movement not in VALID_MOVEMENTS:
        return _fail_result(f"Unknown or missing challenge type: '{movement}'")

    if not video_path or not os.path.exists(video_path):
        return _fail_result("Video file not found")

    # ------------------------------------------------------------------ #
    # Run detector                                                        #
    # ------------------------------------------------------------------ #
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
        return _fail_result(f"Detection error: {exc}")

    # ------------------------------------------------------------------ #
    # Face-presence gate                                                  #
    # ------------------------------------------------------------------ #
    min_face_required = MIN_FACE_FRAMES_EASY if fast_track else MIN_FACE_FRAMES
    face_frames = detection.get("face_detected_frames", 0)

    if face_frames < min_face_required:
        msg = f"Face not visible enough ({face_frames} frames, need {min_face_required})"
        print(f"❌ FAIL: {msg}")
        log_event(
            event="challenge_failed",
            session_id=session_id,
            challenge_id=challenge_id,
            details={"reason": "insufficient_face_presence", "face_frames": face_frames,
                     "required": min_face_required, "movement": movement},
        )
        return _fail_result(msg, face_frames=face_frames)

    # ------------------------------------------------------------------ #
    # Action gate                                                         #
    # ------------------------------------------------------------------ #
    challenge_passed = bool(detection.get("passed", False))
    error_msg        = detection.get("error")

    if not challenge_passed:
        print(f"❌ FAIL: {error_msg}")
        log_event(
            event="challenge_failed",
            session_id=session_id,
            challenge_id=challenge_id,
            details={"reason": "action_not_detected", "movement": movement,
                     "detection": detection},
        )
        return _fail_result(error_msg or "Action not detected", face_frames=face_frames)

    # ------------------------------------------------------------------ #
    # SUCCESS                                                             #
    # ------------------------------------------------------------------ #
    liveness_score = 0.98 if fast_track else 0.96

    # Give a small bonus for head turns with large magnitude
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
            "face_frames": face_frames,
            "detection": detection,
        },
    )

    return {
        "challenge_passed":  True,
        "liveness_score":    liveness_score,
        "action_detected":   movement,
        "action_matched":    True,
        # Legacy compat
        "direction_detected": direction_detected,
        "direction_matched":  direction_matched,
        "error":             None,
    }


# ============================================================================
# HELPER — build a failed-result dict
# ============================================================================

def _fail_result(error: str, face_frames: int = 0) -> dict:
    return {
        "challenge_passed":  False,
        "liveness_score":    0.0,
        "action_detected":   "none",
        "action_matched":    False,
        "direction_detected": "none",
        "direction_matched":  False,
        "error":             error,
    }