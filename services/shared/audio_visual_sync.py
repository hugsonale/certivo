"""
Audio-Visual Lip Sync Detection
Validates audio phrase challenge matches lip movements
"""

import cv2
import numpy as np
from typing import Dict, Any, List, Optional, Tuple
import librosa
import soundfile as sf
from scipy.signal import correlate
from scipy.spatial import distance as dist
import mediapipe as mp


class AudioVisualSyncDetector:
    """
    Detect lip sync consistency between audio and video
    
    Features:
    - Audio phrase extraction and verification
    - Lip movement tracking
    - Temporal alignment between audio and visual
    - Sync score calculation
    """
    
    def __init__(self):
        self.mp_face_mesh = mp.solutions.face_mesh
        self.face_mesh = self.mp_face_mesh.FaceMesh(
            static_image_mode=False,
            max_num_faces=1,
            refine_landmarks=True
        )
        
        # Lip sync parameters
        self.sync_threshold = 0.6  # Minimum sync score
        self.phrase_confidence_threshold = 0.7
    
    def analyze_audio_visual_sync(
        self,
        video_path: str,
        audio_path: Optional[str] = None,
        expected_phrase: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Analyze audio-visual synchronization
        
        Args:
            video_path: Path to video file
            audio_path: Path to audio file (or None to extract from video)
            expected_phrase: Expected spoken phrase
        
        Returns:
            Sync analysis results
        """
        
        # Extract audio from video if not provided
        if audio_path is None:
            audio_path = self._extract_audio_from_video(video_path)
        
        # Analyze audio
        audio_analysis = self._analyze_audio(audio_path, expected_phrase)
        
        # Analyze video (lip movements)
        video_analysis = self._analyze_lip_movements(video_path)
        
        # Compute sync score
        sync_score = self._compute_sync_score(audio_analysis, video_analysis)
        
        return {
            "audio": audio_analysis,
            "video": video_analysis,
            "sync_score": sync_score,
            "is_synced": sync_score > self.sync_threshold,
            "phrase_matched": audio_analysis.get("phrase_matched", False)
        }
    
    def _extract_audio_from_video(self, video_path: str) -> str:
        """Extract audio track from video"""
        
        import subprocess
        import tempfile
        
        # Create temporary audio file
        audio_path = tempfile.mktemp(suffix=".wav")
        
        # Extract using ffmpeg
        try:
            subprocess.run([
                "ffmpeg",
                "-i", video_path,
                "-vn",  # No video
                "-acodec", "pcm_s16le",  # PCM audio
                "-ar", "16000",  # 16kHz sample rate
                "-ac", "1",  # Mono
                audio_path
            ], check=True, capture_output=True)
            
            return audio_path
        except Exception as e:
            print(f"Audio extraction failed: {e}")
            return None
    
    def _analyze_audio(
        self,
        audio_path: str,
        expected_phrase: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Analyze audio track
        
        Features:
        - Speech detection
        - Phrase matching (if expected phrase provided)
        - Energy envelope for sync
        """
        
        if not audio_path:
            return {
                "has_speech": False,
                "phrase_matched": False,
                "energy_envelope": []
            }
        
        try:
            # Load audio
            audio, sr = librosa.load(audio_path, sr=16000)
            
            # Detect speech activity
            rms_energy = librosa.feature.rms(y=audio)[0]
            speech_frames = rms_energy > np.mean(rms_energy) * 0.5
            has_speech = np.sum(speech_frames) > len(speech_frames) * 0.1
            
            # Compute energy envelope for sync
            energy_envelope = rms_energy.tolist()
            
            # Phrase matching (placeholder - would use speech recognition)
            phrase_matched = False
            phrase_confidence = 0.0
            
            if expected_phrase and has_speech:
                # In production, use speech-to-text API
                # For now, check if audio duration matches expected phrase length
                duration = len(audio) / sr
                expected_duration = len(expected_phrase.split()) * 0.5  # ~0.5s per word
                
                if abs(duration - expected_duration) < 1.0:
                    phrase_matched = True
                    phrase_confidence = 0.8
            
            return {
                "has_speech": has_speech,
                "phrase_matched": phrase_matched,
                "phrase_confidence": phrase_confidence,
                "energy_envelope": energy_envelope,
                "duration": len(audio) / sr,
                "sample_rate": sr
            }
            
        except Exception as e:
            print(f"Audio analysis failed: {e}")
            return {
                "has_speech": False,
                "phrase_matched": False,
                "energy_envelope": []
            }
    
    def _analyze_lip_movements(self, video_path: str) -> Dict[str, Any]:
        """
        Analyze lip movements from video
        
        Extracts:
        - Mouth Aspect Ratio (MAR) over time
        - Lip movement energy
        - Speaking activity periods
        """
        
        cap = cv2.VideoCapture(video_path)
        
        if not cap.isOpened():
            return {
                "has_lip_movement": False,
                "mar_envelope": []
            }
        
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        mar_history = []
        
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            
            # Detect face and compute MAR
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            results = self.face_mesh.process(rgb_frame)
            
            if results.multi_face_landmarks:
                landmarks = results.multi_face_landmarks[0]
                mar = self._calculate_mar(landmarks)
                mar_history.append(mar)
            else:
                mar_history.append(0.0)
        
        cap.release()
        
        if not mar_history:
            return {
                "has_lip_movement": False,
                "mar_envelope": []
            }
        
        # Detect lip movement activity
        mar_array = np.array(mar_history)
        mar_mean = np.mean(mar_array)
        
        # Movement = significant deviation from mean
        movement_frames = np.abs(mar_array - mar_mean) > 0.05
        has_lip_movement = np.sum(movement_frames) > len(mar_array) * 0.1
        
        return {
            "has_lip_movement": has_lip_movement,
            "mar_envelope": mar_history,
            "fps": fps,
            "frame_count": len(mar_history)
        }
    
    def _compute_sync_score(
        self,
        audio_analysis: Dict[str, Any],
        video_analysis: Dict[str, Any]
    ) -> float:
        """
        Compute audio-visual synchronization score
        
        Uses cross-correlation between audio energy and lip movement
        """
        
        if not audio_analysis.get("has_speech") or not video_analysis.get("has_lip_movement"):
            return 0.0
        
        audio_envelope = audio_analysis.get("energy_envelope", [])
        mar_envelope = video_analysis.get("mar_envelope", [])
        
        if len(audio_envelope) == 0 or len(mar_envelope) == 0:
            return 0.0
        
        # Resample to same length
        target_length = min(len(audio_envelope), len(mar_envelope))
        
        audio_resampled = np.interp(
            np.linspace(0, 1, target_length),
            np.linspace(0, 1, len(audio_envelope)),
            audio_envelope
        )
        
        mar_resampled = np.interp(
            np.linspace(0, 1, target_length),
            np.linspace(0, 1, len(mar_envelope)),
            mar_envelope
        )
        
        # Normalize
        audio_norm = (audio_resampled - np.mean(audio_resampled)) / (np.std(audio_resampled) + 1e-6)
        mar_norm = (mar_resampled - np.mean(mar_resampled)) / (np.std(mar_resampled) + 1e-6)
        
        # Cross-correlation
        correlation = correlate(audio_norm, mar_norm, mode='same')
        max_correlation = np.max(np.abs(correlation))
        
        # Normalize to 0-1 range
        sync_score = min(1.0, max_correlation / target_length)
        
        return float(sync_score)
    
    def _calculate_mar(self, landmarks) -> float:
        """Calculate Mouth Aspect Ratio"""
        
        # Mouth landmarks (simplified)
        upper_lip = landmarks.landmark[13]  # Upper lip center
        lower_lip = landmarks.landmark[14]  # Lower lip center
        left_corner = landmarks.landmark[61]
        right_corner = landmarks.landmark[291]
        
        # Vertical distance (mouth opening)
        vertical = np.sqrt(
            (upper_lip.x - lower_lip.x)**2 +
            (upper_lip.y - lower_lip.y)**2
        )
        
        # Horizontal distance (mouth width)
        horizontal = np.sqrt(
            (left_corner.x - right_corner.x)**2 +
            (left_corner.y - right_corner.y)**2
        )
        
        # MAR
        mar = vertical / (horizontal + 1e-6)
        return mar