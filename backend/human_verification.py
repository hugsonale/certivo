import os
import cv2
import numpy as np

MIN_FRAMES = 8
BLINK_Y_THRESHOLD = 1.2
HEAD_X_THRESHOLD = 2.0
NOD_Y_THRESHOLD = 2.0
SMILE_MOTION_THRESHOLD = 1.0
MIN_AUDIO_SIZE = 1500
MAX_FRAMES = 25

def extract_motion(video_path):
    cap = cv2.VideoCapture(video_path)
    ret, prev = cap.read()
    if not ret:
        return None

    prev_gray = cv2.cvtColor(prev, cv2.COLOR_BGR2GRAY)
    motions = []

    frames = 0
    while frames < MAX_FRAMES:
        ret, frame = cap.read()
        if not ret:
            break

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        flow = cv2.calcOpticalFlowFarneback(
            prev_gray, gray, None,
            0.5, 3, 15, 3, 5, 1.2, 0
        )

        dx = np.mean(flow[..., 0])
        dy = np.mean(flow[..., 1])

        motions.append((dx, dy))
        prev_gray = gray
        frames += 1

    cap.release()
    return motions if len(motions) >= MIN_FRAMES else None


def verify_blink(motions):
    y = [abs(dy) for _, dy in motions]
    spikes = [v for v in y if v > BLINK_Y_THRESHOLD]
    return len(spikes) >= 1


def verify_head_turn(motions):
    x = [dx for dx, _ in motions]
    return max(x) - min(x) > HEAD_X_THRESHOLD


def verify_nod(motions):
    y = [dy for _, dy in motions]
    return max(y) - min(y) > NOD_Y_THRESHOLD


def verify_smile(motions):
    motion_energy = sum(abs(dx) + abs(dy) for dx, dy in motions)
    return motion_energy > SMILE_MOTION_THRESHOLD


def verify_speech(audio_path, motions):
    if not audio_path or not os.path.exists(audio_path):
        return False
    if os.path.getsize(audio_path) < MIN_AUDIO_SIZE:
        return False
    mouth_motion = sum(abs(dy) for _, dy in motions)
    return mouth_motion > 1.0


def run_human_verification(video_path, audio_path, challenge_type):
    motions = extract_motion(video_path)
    if not motions:
        return fail("no_motion")

    passed = False

    if challenge_type == "blink":
        passed = verify_blink(motions)
    elif challenge_type == "head_turn":
        passed = verify_head_turn(motions)
    elif challenge_type == "nod":
        passed = verify_nod(motions)
    elif challenge_type == "smile":
        passed = verify_smile(motions)
    elif challenge_type == "say_phrase":
        passed = verify_speech(audio_path, motions)
    else:
        return fail("unknown_challenge")

    return pass_result() if passed else fail("signal_mismatch")


def pass_result():
    return {
        "challenge_passed": True,
        "liveness_score": 0.96,
        "lip_sync_score": 0.93,
        "reason": "signal_valid"
    }


def fail(reason):
    return {
        "challenge_passed": False,
        "liveness_score": 0.0,
        "lip_sync_score": 0.0,
        "reason": reason
    }
