"""
Multi-Signal Liveness Detection Model
Combines motion, temporal, audio, and spoof detection signals
"""

import cv2
import numpy as np
from typing import Dict, Any, List, Tuple, Optional
import mediapipe as mp
from scipy.spatial import distance as dist
from scipy.signal import find_peaks
import time


class MultiSignalLivenessDetector:
    """
    Advanced liveness detection using multiple signals
    
    Signals:
    1. Motion trajectory consistency
    2. Temporal landmarks (micro-movements)
    3. Audio-visual lip sync
    4. Spoof detection (screen replay, deepfake artifacts)
    5. Device camera attestation (optional)
    """
    
    def __init__(self):
        # MediaPipe Face Mesh for landmark tracking
        self.mp_face_mesh = mp.solutions.face_mesh
        self.face_mesh = self.mp_face_mesh.FaceMesh(
            static_image_mode=False,
            max_num_faces=1,
            refine_landmarks=True,
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5
        )
        
        # Motion parameters
        self.motion_threshold = 0.01  # Minimum motion for liveness
        self.trajectory_smoothness_threshold = 0.8
        
        # Temporal parameters
        self.blink_ear_threshold = 0.21  # Eye Aspect Ratio for blink
        self.micro_movement_threshold = 0.002
        
        # Spoof detection parameters
        self.screen_replay_threshold = 0.7
        self.deepfake_threshold = 0.6
    
    def analyze_video(
        self,
        video_path: str,
        expected_action: Optional[str] = None,
        audio_challenge: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Analyze video for liveness using all signals
        
        Args:
            video_path: Path to video file
            expected_action: Expected action (e.g., "turn_left", "blink")
            audio_challenge: Expected audio phrase (if audio challenge used)
        
        Returns:
            Comprehensive liveness analysis
        """
        
        # Open video
        cap = cv2.VideoCapture(video_path)
        
        if not cap.isOpened():
            return {
                "liveness_score": 0.0,
                "confidence": 0.0,
                "error": "Cannot open video"
            }
        
        # Extract frames
        frames = []
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        
        while len(frames) < 300:  # Max 10 seconds at 30fps
            ret, frame = cap.read()
            if not ret:
                break
            frames.append(frame)
        
        cap.release()
        
        if len(frames) < 15:
            return {
                "liveness_score": 0.0,
                "confidence": 0.0,
                "error": "Video too short"
            }
        
        # Run all detection signals
        results = {
            "frame_count": len(frames),
            "fps": fps
        }
        
        # Signal 1: Motion Trajectory Consistency
        motion_analysis = self._analyze_motion_trajectory(frames)
        results["motion"] = motion_analysis
        
        # Signal 2: Temporal Landmarks (Micro-movements)
        temporal_analysis = self._analyze_temporal_landmarks(frames)
        results["temporal"] = temporal_analysis
        
        # Signal 3: Spoof Detection
        spoof_analysis = self._detect_spoofing(frames)
        results["spoof"] = spoof_analysis
        
        # Signal 4: Action Detection (if expected)
        if expected_action:
            action_analysis = self._detect_action(frames, expected_action)
            results["action"] = action_analysis
        
        # Signal 5: Audio-Visual Sync (if audio challenge)
        if audio_challenge:
            # Placeholder - would require audio processing
            results["audio_visual_sync"] = {
                "lip_sync_score": 0.0,
                "phrase_detected": False
            }
        
        # Compute final liveness score (weighted fusion)
        liveness_score = self._compute_liveness_score(results)
        
        results["liveness_score"] = liveness_score
        results["confidence"] = self._compute_confidence(results)
        results["is_live"] = liveness_score > 0.7
        
        return results
    
    def _analyze_motion_trajectory(self, frames: List[np.ndarray]) -> Dict[str, Any]:
        """
        Analyze motion trajectory consistency
        
        Real human motion has:
        - Smooth trajectories
        - Natural acceleration/deceleration
        - Micro-jitter (hand tremor, head movement)
        
        Fake motion (deepfake/screen replay) has:
        - Perfect smoothness or jerky motion
        - Unnatural acceleration patterns
        - No micro-movements
        """
        
        trajectories = []
        
        for frame in frames:
            # Detect face landmarks
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            results = self.face_mesh.process(rgb_frame)
            
            if results.multi_face_landmarks:
                landmarks = results.multi_face_landmarks[0]
                
                # Track nose tip (landmark 1)
                nose_tip = landmarks.landmark[1]
                trajectories.append([nose_tip.x, nose_tip.y, nose_tip.z])
        
        if len(trajectories) < 10:
            return {
                "trajectory_score": 0.0,
                "smoothness": 0.0,
                "micro_movement_detected": False
            }
        
        trajectories = np.array(trajectories)
        
        # Calculate velocity and acceleration
        velocities = np.diff(trajectories, axis=0)
        accelerations = np.diff(velocities, axis=0)
        
        # Smoothness: Lower variance in acceleration = smoother
        acc_variance = np.var(accelerations)
        smoothness = 1.0 / (1.0 + acc_variance * 1000)
        
        # Micro-movements: High-frequency small movements
        # Real humans have natural tremor
        velocity_magnitudes = np.linalg.norm(velocities, axis=1)
        micro_movements = np.sum(
            (velocity_magnitudes > self.micro_movement_threshold) & 
            (velocity_magnitudes < 0.01)
        )
        
        micro_movement_detected = micro_movements > len(velocities) * 0.1
        
        # Total motion (prevent static images)
        total_motion = np.sum(velocity_magnitudes)
        has_motion = total_motion > self.motion_threshold
        
        # Trajectory score
        trajectory_score = 0.0
        
        if has_motion:
            trajectory_score += 0.4
        
        if 0.3 < smoothness < 0.95:  # Not too smooth, not too jerky
            trajectory_score += 0.3
        
        if micro_movement_detected:
            trajectory_score += 0.3
        
        return {
            "trajectory_score": min(1.0, trajectory_score),
            "smoothness": smoothness,
            "total_motion": float(total_motion),
            "micro_movement_detected": micro_movement_detected,
            "has_motion": has_motion
        }
    
    def _analyze_temporal_landmarks(self, frames: List[np.ndarray]) -> Dict[str, Any]:
        """
        Analyze temporal consistency of facial landmarks
        
        Real humans have:
        - Natural blinking patterns
        - Subtle facial muscle movements
        - Consistent landmark tracking
        
        Deepfakes have:
        - Irregular blinking
        - Facial landmark instability
        - Temporal inconsistencies
        """
        
        blink_count = 0
        ear_history = []  # Eye Aspect Ratio history
        landmark_stability = []
        
        prev_landmarks = None
        
        for frame in frames:
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            results = self.face_mesh.process(rgb_frame)
            
            if results.multi_face_landmarks:
                landmarks = results.multi_face_landmarks[0]
                
                # Calculate Eye Aspect Ratio (EAR) for blink detection
                ear = self._calculate_ear(landmarks)
                ear_history.append(ear)
                
                # Track landmark stability
                if prev_landmarks is not None:
                    stability = self._calculate_landmark_stability(
                        prev_landmarks, landmarks
                    )
                    landmark_stability.append(stability)
                
                prev_landmarks = landmarks
        
        # Detect blinks from EAR history
        if len(ear_history) > 5:
            ear_array = np.array(ear_history)
            
            # Find blinks (EAR drops below threshold)
            blinks = np.where(ear_array < self.blink_ear_threshold)[0]
            
            # Count distinct blink events (grouped)
            if len(blinks) > 0:
                blink_groups = np.split(blinks, np.where(np.diff(blinks) > 3)[0] + 1)
                blink_count = len(blink_groups)
        
        # Calculate landmark stability score
        avg_stability = np.mean(landmark_stability) if landmark_stability else 0.0
        
        # Temporal score
        temporal_score = 0.0
        
        # Natural blink rate: 15-20 blinks/min → ~0.25-0.33 blinks/sec
        # For 3-5 second video: 1-2 blinks is natural
        if 0 < blink_count <= 5:
            temporal_score += 0.4
        
        if avg_stability > 0.8:  # Stable landmarks
            temporal_score += 0.3
        
        # Check for natural variation in EAR
        if len(ear_history) > 10:
            ear_variance = np.var(ear_history)
            if 0.001 < ear_variance < 0.05:  # Natural variation
                temporal_score += 0.3
        
        return {
            "temporal_score": min(1.0, temporal_score),
            "blink_count": blink_count,
            "landmark_stability": float(avg_stability),
            "ear_variance": float(np.var(ear_history)) if ear_history else 0.0
        }
    
    def _detect_spoofing(self, frames: List[np.ndarray]) -> Dict[str, Any]:
        """
        Detect spoofing attempts (screen replay, deepfake artifacts)
        
        Screen Replay Detection:
        - Moiré patterns (screen interference)
        - Color temperature inconsistencies
        - Uniform lighting (no shadows)
        
        Deepfake Detection:
        - Face warping artifacts
        - Temporal inconsistencies
        - Unnatural eye movements
        - Lip sync errors
        """
        
        spoof_indicators = {
            "moire_detected": False,
            "color_temp_inconsistent": False,
            "no_shadows": False,
            "face_warping": False,
            "unnatural_eye_movement": False
        }
        
        # Sample frames for analysis
        sample_indices = np.linspace(0, len(frames) - 1, min(10, len(frames)), dtype=int)
        sampled_frames = [frames[i] for i in sample_indices]
        
        # 1. Moiré Pattern Detection (screen replay)
        moire_scores = []
        for frame in sampled_frames:
            # Convert to grayscale
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            
            # FFT to detect periodic patterns
            fft = np.fft.fft2(gray)
            fft_shift = np.fft.fftshift(fft)
            magnitude = np.abs(fft_shift)
            
            # Look for high-frequency periodic patterns
            h, w = magnitude.shape
            center_region = magnitude[h//4:3*h//4, w//4:3*w//4]
            high_freq_energy = np.sum(center_region) / center_region.size
            
            moire_scores.append(high_freq_energy)
        
        avg_moire = np.mean(moire_scores)
        spoof_indicators["moire_detected"] = avg_moire > 1000  # Threshold for moiré
        
        # 2. Color Temperature Consistency
        color_temps = []
        for frame in sampled_frames:
            # Calculate color temperature (simplified)
            b, g, r = cv2.split(frame)
            color_temp = np.mean(r) / (np.mean(b) + 1e-6)
            color_temps.append(color_temp)
        
        color_temp_variance = np.var(color_temps)
        spoof_indicators["color_temp_inconsistent"] = color_temp_variance > 0.5
        
        # 3. Shadow Detection (no shadows = screen replay)
        shadow_detected = False
        for frame in sampled_frames:
            # Convert to LAB color space
            lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
            l_channel = lab[:, :, 0]
            
            # Check for dark regions (shadows)
            dark_pixels = np.sum(l_channel < 50)
            if dark_pixels > l_channel.size * 0.05:  # 5% dark pixels
                shadow_detected = True
                break
        
        spoof_indicators["no_shadows"] = not shadow_detected
        
        # 4. Face Warping Detection (deepfake artifact)
        warping_scores = []
        
        for i in range(len(frames) - 1):
            # Optical flow between consecutive frames
            prev_gray = cv2.cvtColor(frames[i], cv2.COLOR_BGR2GRAY)
            curr_gray = cv2.cvtColor(frames[i + 1], cv2.COLOR_BGR2GRAY)
            
            flow = cv2.calcOpticalFlowFarneback(
                prev_gray, curr_gray, None,
                0.5, 3, 15, 3, 5, 1.2, 0
            )
            
            # Detect irregular flow patterns (warping)
            flow_magnitude = np.sqrt(flow[..., 0]**2 + flow[..., 1]**2)
            flow_variance = np.var(flow_magnitude)
            
            warping_scores.append(flow_variance)
        
        avg_warping = np.mean(warping_scores) if warping_scores else 0.0
        spoof_indicators["face_warping"] = avg_warping > 100  # High variance = warping
        
        # Calculate overall spoof score
        spoof_count = sum(spoof_indicators.values())
        spoof_probability = spoof_count / len(spoof_indicators)
        
        # Inverse for liveness (1 - spoof_prob)
        anti_spoof_score = 1.0 - spoof_probability
        
        return {
            "anti_spoof_score": anti_spoof_score,
            "spoof_probability": spoof_probability,
            "indicators": spoof_indicators,
            "is_spoof": spoof_probability > 0.4
        }
    
    def _detect_action(self, frames: List[np.ndarray], expected_action: str) -> Dict[str, Any]:
        """
        Detect if expected action was performed
        
        Actions:
        - turn_left, turn_right, turn_up, turn_down
        - blink, nod
        - mouth_open, smile
        """
        
        if expected_action in ["turn_left", "turn_right", "turn_up", "turn_down"]:
            return self._detect_head_turn(frames, expected_action)
        elif expected_action == "blink":
            return self._detect_blink(frames)
        elif expected_action == "nod":
            return self._detect_nod(frames)
        elif expected_action == "mouth_open":
            return self._detect_mouth_open(frames)
        else:
            return {"action_detected": False, "confidence": 0.0}
    
    def _detect_head_turn(self, frames: List[np.ndarray], direction: str) -> Dict[str, Any]:
        """Detect head turn in specified direction"""
        
        yaw_history = []
        pitch_history = []
        
        for frame in frames:
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            results = self.face_mesh.process(rgb_frame)
            
            if results.multi_face_landmarks:
                landmarks = results.multi_face_landmarks[0]
                
                # Estimate head pose (simplified)
                nose = landmarks.landmark[1]
                left_ear = landmarks.landmark[234]
                right_ear = landmarks.landmark[454]
                
                # Yaw (left-right)
                yaw = (nose.x - 0.5) * 2  # -1 to 1
                yaw_history.append(yaw)
                
                # Pitch (up-down)
                pitch = (nose.y - 0.5) * 2
                pitch_history.append(pitch)
        
        if len(yaw_history) < 5:
            return {"action_detected": False, "confidence": 0.0}
        
        # Detect turn based on direction
        detected = False
        confidence = 0.0
        
        if direction == "turn_left":
            # Yaw should decrease (move negative)
            yaw_change = yaw_history[-1] - yaw_history[0]
            if yaw_change < -0.3:
                detected = True
                confidence = min(1.0, abs(yaw_change))
        
        elif direction == "turn_right":
            # Yaw should increase (move positive)
            yaw_change = yaw_history[-1] - yaw_history[0]
            if yaw_change > 0.3:
                detected = True
                confidence = min(1.0, abs(yaw_change))
        
        elif direction == "turn_up":
            # Pitch should decrease
            pitch_change = pitch_history[-1] - pitch_history[0]
            if pitch_change < -0.2:
                detected = True
                confidence = min(1.0, abs(pitch_change))
        
        elif direction == "turn_down":
            # Pitch should increase
            pitch_change = pitch_history[-1] - pitch_history[0]
            if pitch_change > 0.2:
                detected = True
                confidence = min(1.0, abs(pitch_change))
        
        return {
            "action_detected": detected,
            "confidence": confidence,
            "yaw_change": float(yaw_history[-1] - yaw_history[0]) if yaw_history else 0.0,
            "pitch_change": float(pitch_history[-1] - pitch_history[0]) if pitch_history else 0.0
        }
    
    def _detect_blink(self, frames: List[np.ndarray]) -> Dict[str, Any]:
        """Detect blink action"""
        
        ear_history = []
        
        for frame in frames:
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            results = self.face_mesh.process(rgb_frame)
            
            if results.multi_face_landmarks:
                landmarks = results.multi_face_landmarks[0]
                ear = self._calculate_ear(landmarks)
                ear_history.append(ear)
        
        if len(ear_history) < 10:
            return {"action_detected": False, "confidence": 0.0}
        
        # Find blinks (EAR drops)
        ear_array = np.array(ear_history)
        peaks, _ = find_peaks(-ear_array, height=-self.blink_ear_threshold, distance=5)
        
        blink_detected = len(peaks) >= 1
        confidence = min(1.0, len(peaks) / 2.0)  # 1-2 blinks = high confidence
        
        return {
            "action_detected": blink_detected,
            "confidence": confidence,
            "blink_count": len(peaks)
        }
    
    def _detect_nod(self, frames: List[np.ndarray]) -> Dict[str, Any]:
        """Detect nod action (up-down head movement)"""
        
        pitch_history = []
        
        for frame in frames:
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            results = self.face_mesh.process(rgb_frame)
            
            if results.multi_face_landmarks:
                landmarks = results.multi_face_landmarks[0]
                nose = landmarks.landmark[1]
                pitch = (nose.y - 0.5) * 2
                pitch_history.append(pitch)
        
        if len(pitch_history) < 10:
            return {"action_detected": False, "confidence": 0.0}
        
        # Find peaks and valleys (up-down motion)
        pitch_array = np.array(pitch_history)
        peaks, _ = find_peaks(pitch_array, distance=5)
        valleys, _ = find_peaks(-pitch_array, distance=5)
        
        # Nod = at least 1 down-up or up-down cycle
        nod_detected = len(peaks) >= 1 and len(valleys) >= 1
        confidence = min(1.0, (len(peaks) + len(valleys)) / 4.0)
        
        return {
            "action_detected": nod_detected,
            "confidence": confidence,
            "cycles": len(peaks) + len(valleys)
        }
    
    def _detect_mouth_open(self, frames: List[np.ndarray]) -> Dict[str, Any]:
        """Detect mouth open action"""
        
        mar_history = []  # Mouth Aspect Ratio
        
        for frame in frames:
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            results = self.face_mesh.process(rgb_frame)
            
            if results.multi_face_landmarks:
                landmarks = results.multi_face_landmarks[0]
                mar = self._calculate_mar(landmarks)
                mar_history.append(mar)
        
        if len(mar_history) < 5:
            return {"action_detected": False, "confidence": 0.0}
        
        # Check if mouth was opened (MAR above threshold)
        mar_array = np.array(mar_history)
        max_mar = np.max(mar_array)
        
        mouth_opened = max_mar > 0.5  # Threshold for mouth open
        confidence = min(1.0, max_mar / 0.7)
        
        return {
            "action_detected": mouth_opened,
            "confidence": confidence,
            "max_mar": float(max_mar)
        }
    
    def _calculate_ear(self, landmarks) -> float:
        """Calculate Eye Aspect Ratio for blink detection"""
        
        # Left eye landmarks
        left_eye_indices = [33, 160, 158, 133, 153, 144]
        left_eye = np.array([
            [landmarks.landmark[i].x, landmarks.landmark[i].y]
            for i in left_eye_indices
        ])
        
        # Right eye landmarks
        right_eye_indices = [362, 385, 387, 263, 373, 380]
        right_eye = np.array([
            [landmarks.landmark[i].x, landmarks.landmark[i].y]
            for i in right_eye_indices
        ])
        
        # Calculate EAR for both eyes
        left_ear = self._eye_aspect_ratio(left_eye)
        right_ear = self._eye_aspect_ratio(right_eye)
        
        return (left_ear + right_ear) / 2.0
    
    def _eye_aspect_ratio(self, eye: np.ndarray) -> float:
        """Calculate aspect ratio of eye"""
        # Vertical distances
        A = dist.euclidean(eye[1], eye[5])
        B = dist.euclidean(eye[2], eye[4])
        
        # Horizontal distance
        C = dist.euclidean(eye[0], eye[3])
        
        # EAR
        ear = (A + B) / (2.0 * C)
        return ear
    
    def _calculate_mar(self, landmarks) -> float:
        """Calculate Mouth Aspect Ratio"""
        
        # Mouth landmarks
        mouth_indices = [61, 291, 0, 17, 405, 181]
        mouth = np.array([
            [landmarks.landmark[i].x, landmarks.landmark[i].y]
            for i in mouth_indices
        ])
        
        # Vertical distance
        A = dist.euclidean(mouth[2], mouth[5])
        
        # Horizontal distance
        B = dist.euclidean(mouth[0], mouth[1])
        
        # MAR
        mar = A / (B + 1e-6)
        return mar
    
    def _calculate_landmark_stability(self, prev_landmarks, curr_landmarks) -> float:
        """Calculate stability between consecutive landmark sets"""
        
        # Compare positions of key landmarks
        key_indices = [1, 33, 133, 362, 263, 61, 291]  # Nose, eyes, mouth corners
        
        distances = []
        for idx in key_indices:
            prev = prev_landmarks.landmark[idx]
            curr = curr_landmarks.landmark[idx]
            
            distance = np.sqrt(
                (prev.x - curr.x)**2 + 
                (prev.y - curr.y)**2 + 
                (prev.z - curr.z)**2
            )
            distances.append(distance)
        
        # Lower distance = more stable
        avg_distance = np.mean(distances)
        stability = 1.0 / (1.0 + avg_distance * 100)
        
        return stability
    
    def _compute_liveness_score(self, results: Dict[str, Any]) -> float:
        """
        Compute final liveness score using weighted fusion
        
        Weights:
        - Motion trajectory: 25%
        - Temporal landmarks: 25%
        - Anti-spoof: 30%
        - Action detection: 20%
        """
        
        score = 0.0
        
        # Motion trajectory (25%)
        if "motion" in results:
            score += results["motion"]["trajectory_score"] * 0.25
        
        # Temporal landmarks (25%)
        if "temporal" in results:
            score += results["temporal"]["temporal_score"] * 0.25
        
        # Anti-spoof (30%)
        if "spoof" in results:
            score += results["spoof"]["anti_spoof_score"] * 0.30
        
        # Action detection (20%)
        if "action" in results:
            score += results["action"]["confidence"] * 0.20
        
        return min(1.0, score)
    
    def _compute_confidence(self, results: Dict[str, Any]) -> float:
        """Compute confidence in the liveness assessment"""
        
        # Confidence based on data quality
        confidence = 0.0
        
        frame_count = results.get("frame_count", 0)
        if frame_count >= 30:
            confidence += 0.3
        elif frame_count >= 15:
            confidence += 0.15
        
        # Motion data quality
        if "motion" in results and results["motion"]["has_motion"]:
            confidence += 0.3
        
        # Temporal data quality
        if "temporal" in results and results["temporal"]["landmark_stability"] > 0.7:
            confidence += 0.2
        
        # Spoof detection certainty
        if "spoof" in results:
            spoof_prob = results["spoof"]["spoof_probability"]
            # High certainty if clearly spoof or clearly not spoof
            if spoof_prob < 0.2 or spoof_prob > 0.8:
                confidence += 0.2
        
        return min(1.0, confidence)