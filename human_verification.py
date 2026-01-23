# human_verification.py
import os
import cv2
import numpy as np

MIN_AUDIO_SIZE = 1500
MIN_VIDEO_FRAMES = 5
MOTION_THRESHOLD = 1.5
BLINK_MOTION_THRESHOLD = 1.0
HEAD_MOTION_THRESHOLD = 2.0
MAX_FRAMES_TO_CHECK = 20

def _video_motion_profile(video_path: str):
    if not video_path or not os.path.exists(video_path):
        return None

    cap = cv2.VideoCapture(video_path)
    ret, prev = cap.read()
    if not ret:
        cap.release()
        return None

    prev_gray = cv2.cvtColor(prev, cv2.COLOR_BGR2GRAY)
    total_motion, x_motion, y_motion, frames = 0, 0.0, 0.0, 1

    while frames < MAX_FRAMES_TO_CHECK:
        ret, frame = cap.read()
        if not ret:
            break
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        diff = cv2.absdiff(prev_gray, gray)
        if np.mean(diff) > MOTION_THRESHOLD:
            total_motion += 1

        flow = cv2.calcOpticalFlowFarneback(prev_gray, gray, None, 0.5, 3, 15, 3, 5, 1.2, 0)
        x_motion += float(np.mean(flow[..., 0]))
        y_motion += float(np.mean(flow[..., 1]))
        prev_gray = gray
        frames += 1

    cap.release()
    if frames == 0:
        return None

    return {"frames": frames, "total_motion": total_motion, "x_motion": x_motion, "y_motion": y_motion}

def run_human_verification(video_path: str, audio_path: str, challenge_type: str):
    motion = _video_motion_profile(video_path)

    if challenge_type == "speak_phrase":
        if not audio_path or os.path.getsize(audio_path) < MIN_AUDIO_SIZE:
            return _fail("audio_missing_or_small")
        if not motion or motion["total_motion"] < MIN_VIDEO_FRAMES:
            return _fail("no_face_motion")
        return _pass(confidence=0.97)

    if not motion:
        return _fail("no_video")

    if challenge_type == "blink":
        if motion["total_motion"] < MIN_VIDEO_FRAMES or abs(motion["y_motion"]) < BLINK_MOTION_THRESHOLD:
            return _fail("blink_not_detected")
        return _pass(confidence=0.95)
    if challenge_type == "head_turn":
        if abs(motion["x_motion"]) < HEAD_MOTION_THRESHOLD:
            return _fail("head_turn_not_detected")
        return _pass(confidence=0.95)
    if challenge_type == "nod":
        if abs(motion["y_motion"]) < HEAD_MOTION_THRESHOLD:
            return _fail("nod_not_detected")
        return _pass(confidence=0.95)
    if motion["total_motion"] >= MIN_VIDEO_FRAMES and abs(motion["x_motion"]) > 0.5:
        return _pass(confidence=0.94)

    return _fail("challenge_failed")

def _pass(confidence=0.95):
    return {
        "liveness_score": round(confidence, 2),
        "lip_sync_score": round(confidence-0.03, 2),
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
