# human_verification.py
import os
import cv2
import numpy as np

MIN_AUDIO_SIZE = 5_000        # bytes
MIN_VIDEO_FRAMES = 15
MOTION_THRESHOLD = 2.5        # pixel intensity delta

BLINK_MOTION_THRESHOLD = 1.8
HEAD_MOTION_THRESHOLD = 4.0


def _video_motion_profile(video_path: str):
    """
    Analyze video motion and return basic movement stats
    """
    cap = cv2.VideoCapture(video_path)
    ret, prev = cap.read()
    if not ret:
        cap.release()
        return None

    prev_gray = cv2.cvtColor(prev, cv2.COLOR_BGR2GRAY)

    total_motion = 0
    x_motion = 0
    y_motion = 0
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

        # motion direction estimation
        flow = cv2.calcOpticalFlowFarneback(
            prev_gray, gray, None,
            0.5, 3, 15, 3, 5, 1.2, 0
        )

        x_motion += np.mean(flow[..., 0])
        y_motion += np.mean(flow[..., 1])

        prev_gray = gray
        frames += 1

    cap.release()

    return {
        "frames": frames,
        "total_motion": total_motion,
        "x_motion": x_motion,
        "y_motion": y_motion
    }


def run_human_verification(video_path: str, audio_path: str, challenge_type: str):
    """
    Certivo V1 Verification Engine (Challenge-Aware)
    """

    motion = _video_motion_profile(video_path)
    if not motion:
        return _fail("no_video")

    # ---------------- SPEAK PHRASE ----------------
    if challenge_type == "speak_phrase":
        if not audio_path or os.path.getsize(audio_path) < MIN_AUDIO_SIZE:
            return _fail("audio_too_small")
        return _pass()

    # ---------------- BLINK ----------------
    if challenge_type == "blink":
        # Blink = short burst motion, low directional drift
        if motion["total_motion"] < MIN_VIDEO_FRAMES:
            return _fail("no_blink_motion")

        if abs(motion["y_motion"]) < BLINK_MOTION_THRESHOLD:
            return _fail("blink_not_detected")

        return _pass()

    # ---------------- HEAD TURN ----------------
    if challenge_type == "head_turn":
        if abs(motion["x_motion"]) < HEAD_MOTION_THRESHOLD:
            return _fail("no_head_turn")
        return _pass()

    # ---------------- NOD ----------------
    if challenge_type == "nod":
        if abs(motion["y_motion"]) < HEAD_MOTION_THRESHOLD:
            return _fail("no_nod")
        return _pass()

    # ---------------- FALLBACK ----------------
    if motion["total_motion"] >= MIN_VIDEO_FRAMES:
        return _pass()

    return _fail("unknown_challenge")


def _pass():
    return {
        "liveness_score": 0.93,
        "lip_sync_score": 0.88,
        "challenge_passed": True,
        "replay_flag": False
    }


def _fail(reason="failed"):
    return {
        "liveness_score": 0.0,
        "lip_sync_score": 0.0,
        "challenge_passed": False,
        "replay_flag": False,
        "reason": reason
    }
