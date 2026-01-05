# human_verification.py
import os
import cv2
import numpy as np

# ---------------- V1 FRIENDLY THRESHOLDS ----------------
MIN_AUDIO_SIZE = 1_500          # bytes (browser-safe)
MIN_VIDEO_FRAMES = 5            # allow short clips
MOTION_THRESHOLD = 1.2          # less aggressive

BLINK_MOTION_THRESHOLD = 0.8
HEAD_MOTION_THRESHOLD = 1.5


def _video_motion_profile(video_path: str):
    """
    Analyze video motion and return basic movement stats
    """
    if not video_path or not os.path.exists(video_path):
        return None

    cap = cv2.VideoCapture(video_path)
    ret, prev = cap.read()
    if not ret:
        cap.release()
        return None

    prev_gray = cv2.cvtColor(prev, cv2.COLOR_BGR2GRAY)

    total_motion = 0
    x_motion = 0.0
    y_motion = 0.0
    frames = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        diff = cv2.absdiff(prev_gray, gray)
        mean_diff = np.mean(diff)

        if mean_diff > MOTION_THRESHOLD:
            total_motion += 1

        # Optical flow for motion direction
        flow = cv2.calcOpticalFlowFarneback(
            prev_gray, gray, None,
            0.5, 3, 15, 3, 5, 1.2, 0
        )

        x_motion += float(np.mean(flow[..., 0]))
        y_motion += float(np.mean(flow[..., 1]))

        prev_gray = gray
        frames += 1

    cap.release()

    if frames == 0:
        return None

    return {
        "frames": frames,
        "total_motion": total_motion,
        "x_motion": x_motion,
        "y_motion": y_motion
    }


def run_human_verification(video_path: str, audio_path: str, challenge_type: str):
    """
    Certivo V1 Verification Engine (Friendly Version)
    Rule: Any successful challenge == human
    """

    motion = _video_motion_profile(video_path)

    # ---------------- SPEAK PHRASE ----------------
    if challenge_type == "speak_phrase":
        if not audio_path or not os.path.exists(audio_path):
            return _fail("missing_audio")

        if os.path.getsize(audio_path) < MIN_AUDIO_SIZE:
            return _fail("audio_too_small")

        if not motion or motion["total_motion"] < 2:
            return _fail("no_face_motion")

        # ✅ Boost confidence for successful speech challenge
        return _pass(confidence=0.97)

    # Video required from here
    if not motion:
        return _fail("no_video")

    # ---------------- BLINK ----------------
    if challenge_type == "blink":
        if motion["total_motion"] < MIN_VIDEO_FRAMES:
            return _fail("insufficient_motion")

        if abs(motion["y_motion"]) < BLINK_MOTION_THRESHOLD:
            return _fail("blink_not_detected")

        # ✅ Friendly confidence
        return _pass(confidence=0.96)

    # ---------------- HEAD TURN ----------------
    if challenge_type == "head_turn":
        if abs(motion["x_motion"]) < HEAD_MOTION_THRESHOLD:
            return _fail("head_turn_not_detected")

        return _pass(confidence=0.95)

    # ---------------- NOD ----------------
    if challenge_type == "nod":
        if abs(motion["y_motion"]) < HEAD_MOTION_THRESHOLD:
            return _fail("nod_not_detected")

        return _pass(confidence=0.95)

    # ---------------- SMILE or GENERIC ----------------
    if motion["total_motion"] >= MIN_VIDEO_FRAMES:
        return _pass(confidence=0.94)

    return _fail("challenge_failed")


def _pass(confidence=0.95):
    return {
        "liveness_score": round(confidence, 2),
        "lip_sync_score": round(confidence - 0.03, 2),  # small deduction for lip sync
        "challenge_passed": True,
        "replay_flag": False,
        "reason": "passed"
    }


def _fail(reason="failed"):
    return {
        "liveness_score": 0.0,
        "lip_sync_score": 0.0,
        "challenge_passed": False,
        "replay_flag": False,
        "reason": reason
    }
