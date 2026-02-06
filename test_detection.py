import cv2
import os

# Test video analysis without running full server
def test_video(video_path):
    """Quick test of face detection"""
    if not os.path.exists(video_path):
        print(f"❌ File not found: {video_path}")
        return
    
    cap = cv2.VideoCapture(video_path)
    
    # Load Haar Cascade
    face_cascade_path = cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
    face_cascade = cv2.CascadeClassifier(face_cascade_path)
    
    frame_count = 0
    faces_detected = 0
    face_positions = []
    
    print("\n🔍 Analyzing video...")
    
    while frame_count < 30:
        ret, frame = cap.read()
        if not ret:
            break
        
        # Detect faces
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30))
        
        if len(faces) > 0:
            faces_detected += 1
            face = faces[0]  # Take first face
            center_x = face[0] + face[2] / 2
            face_positions.append(center_x)
            print(f"Frame {frame_count}: Face detected at X={center_x:.2f}")
        else:
            print(f"Frame {frame_count}: No face detected")
        
        frame_count += 1
    
    cap.release()
    
    print(f"\n📊 Summary:")
    print(f"Total frames analyzed: {frame_count}")
    print(f"Faces detected in: {faces_detected} frames")
    print(f"Face positions tracked: {len(face_positions)}")
    
    # Calculate movement
    if len(face_positions) >= 2:
        net_movement = face_positions[-1] - face_positions[0]
        print(f"Net movement: {net_movement:.2f}px")
        
        if net_movement > 15:
            print("✅ Detected: RIGHT movement")
        elif net_movement < -15:
            print("✅ Detected: LEFT movement")
        else:
            print("⚠️ Movement too small to detect direction")
    else:
        print("❌ Not enough face positions to calculate movement")

# Test with a sample video
print("=" * 50)
print("VIDEO DETECTION TESTER")
print("=" * 50)
print("\nInstructions:")
print("1. Complete a challenge and note the temp file path from logs")
print("2. Copy that .webm file before it gets deleted")
print("3. Run: python test_detection.py")
print("4. Enter the path when prompted")
print("\nOR manually test:")
video_path = input("\nEnter path to test video (or press Enter to skip): ").strip()

if video_path:
    test_video(video_path)
else:
    print("Skipped. Record a video first!")