
'''

# human_verification.py
import cv2
import mediapipe as mp
import time
import speech_recognition as sr

def run_human_verification():
    # ----------- Blink / head movement detection -------------------
    mp_face_mesh = mp.solutions.face_mesh
    face_mesh = mp_face_mesh.FaceMesh(
        min_detection_confidence=0.5,
        min_tracking_confidence=0.5
    )

    cap = cv2.VideoCapture(0)
    blink_detected = False
    start_time = time.time()
    duration = 8

    print("\n[Certivo] Challenge: Blink once in 8 seconds")

    while time.time() - start_time < duration:
        ret, frame = cap.read()
        if not ret:
            continue

        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = face_mesh.process(frame_rgb)

        if results.multi_face_landmarks:
            for face_landmarks in results.multi_face_landmarks:
                left_eye_top = face_landmarks.landmark[159]
                left_eye_bottom = face_landmarks.landmark[145]
                eye_ratio = abs(left_eye_top.y - left_eye_bottom.y)
                if eye_ratio > 0.02:
                    blink_detected = True

        cv2.imshow("Certivo Live Verification", frame)
        if cv2.waitKey(1) & 0xFF == 27:
            break

    cap.release()
    cv2.destroyAllWindows()

    # ----------- Speech Challenge -------------------
    recognizer = sr.Recognizer()
    mic = sr.Microphone()

    phrase = "I am human"
    print(f"[Certivo] Please say: \"{phrase}\"")

    with mic as source:
        recognizer.adjust_for_ambient_noise(source)
        audio = recognizer.listen(source)

    try:
        text = recognizer.recognize_google(audio)
        phrase_passed = phrase.lower() in text.lower()
    except:
        phrase_passed = False

    # ----------- Scores -------------------
    liveness_score = 0.95 if blink_detected else 0.5
    lip_sync_score = 0.92 if phrase_passed else 0.4
    challenge_passed = blink_detected and phrase_passed

    result = {
        "liveness_score": liveness_score,
        "lip_sync_score": lip_sync_score,
        "challenge_passed": challenge_passed,
        "blink_detected": blink_detected,
        "phrase_correct": phrase_passed
    }

    return result

    
    '''