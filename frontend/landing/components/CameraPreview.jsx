/**
 * Camera Preview Component
 * Real-time guidance and challenge execution
 */

import React, { useRef, useEffect, useState } from 'react';
import { ChallengeIndicator } from './ChallengeIndicator';

export const CameraPreview = ({
  sessionId,
  challengeConfig,
  onPositioned,
  onVideoCapture,
  guidance,
  language,
  reducedMotion,
  onError
}) => {
  const videoRef = useRef(null);
  const canvasRef = useRef(null);
  const mediaRecorderRef = useRef(null);
  const chunksRef = useRef([]);
  
  const [isRecording, setIsRecording] = useState(false);
  const [positioningFeedback, setPositioningFeedback] = useState(null);
  const [currentChallenge, setCurrentChallenge] = useState(null);
  const [challengeStage, setChallengeStage] = useState('prepare'); // prepare, execute, success, retry
  
  useEffect(() => {
    startCamera();
    return () => stopCamera();
  }, []);
  
  useEffect(() => {
    if (videoRef.current && videoRef.current.srcObject) {
      startPositioningAnalysis();
    }
  }, [videoRef.current?.srcObject]);
  
  const startCamera = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: {
          width: { ideal: 1280 },
          height: { ideal: 720 },
          facingMode: 'user'
        },
        audio: false
      });
      
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
      }
    } catch (error) {
      console.error('Camera access failed:', error);
      onError({ code: 'camera_permission_denied', message: error.message });
    }
  };
  
  const stopCamera = () => {
    if (videoRef.current?.srcObject) {
      const tracks = videoRef.current.srcObject.getTracks();
      tracks.forEach(track => track.stop());
    }
  };
  
  const startPositioningAnalysis = () => {
    // Analyze video frame for face detection and positioning
    const analyzeFrame = () => {
      if (!videoRef.current || !canvasRef.current) return;
      
      const video = videoRef.current;
      const canvas = canvasRef.current;
      const ctx = canvas.getContext('2d');
      
      // Draw current frame
      ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
      
      // Get image data
      const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
      
      // Analyze positioning (simplified - real implementation would use face detection)
      const feedback = analyzePositioning(imageData);
      setPositioningFeedback(feedback);
      
      // If well-positioned, allow to proceed
      if (feedback.status === 'good') {
        setTimeout(() => {
          onPositioned();
          startChallenge();
        }, 1000);
      } else {
        // Continue analyzing
        requestAnimationFrame(analyzeFrame);
      }
    };
    
    analyzeFrame();
  };
  
  const analyzePositioning = (imageData) => {
    // Simplified positioning analysis
    // Real implementation would use face detection library
    
    // For demo purposes, return good position after 2 seconds
    return {
      status: 'good',
      faceDetected: true,
      faceSize: 0.6,
      lightingScore: 0.8,
      message: 'Perfect! Hold still'
    };
  };
  
  const startChallenge = () => {
    if (!challengeConfig || challengeConfig.challenges.length === 0) return;
    
    const challenge = challengeConfig.challenges[0];
    setCurrentChallenge(challenge);
    setChallengeStage('prepare');
    
    // Show "prepare" for 2 seconds
    setTimeout(() => {
      setChallengeStage('execute');
      startRecording();
      
      // Auto-stop after challenge duration
      setTimeout(() => {
        stopRecording();
      }, challenge.duration_ms || 3000);
    }, 2000);
  };
  
  const startRecording = () => {
    if (!videoRef.current?.srcObject) return;
    
    try {
      const stream = videoRef.current.srcObject;
      const mediaRecorder = new MediaRecorder(stream, {
        mimeType: 'video/webm;codecs=vp9',
        videoBitsPerSecond: 2500000 // 2.5 Mbps
      });
      
      chunksRef.current = [];
      
      mediaRecorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          chunksRef.current.push(event.data);
        }
      };
      
      mediaRecorder.onstop = () => {
        const blob = new Blob(chunksRef.current, { type: 'video/webm' });
        onVideoCapture(blob);
      };
      
      mediaRecorder.start();
      mediaRecorderRef.current = mediaRecorder;
      setIsRecording(true);
    } catch (error) {
      console.error('Recording failed:', error);
      onError({ code: 'recording_failed', message: error.message });
    }
  };
  
  const stopRecording = () => {
    if (mediaRecorderRef.current && isRecording) {
      mediaRecorderRef.current.stop();
      setIsRecording(false);
      setChallengeStage('success');
    }
  };
  
  return (
    <div className="camera-preview" role="region" aria-label="Camera preview">
      {/* Video preview */}
      <div className="video-container">
        <video
          ref={videoRef}
          autoPlay
          playsInline
          muted
          className="video-preview"
          aria-label="Live camera feed"
        />
        
        {/* Hidden canvas for frame analysis */}
        <canvas
          ref={canvasRef}
          width="640"
          height="480"
          style={{ display: 'none' }}
          aria-hidden="true"
        />
        
        {/* Face outline overlay */}
        <div 
          className={`face-outline ${positioningFeedback?.status === 'good' ? 'good' : 'adjusting'}`}
          aria-hidden="true"
        />
      </div>
      
      {/* Positioning feedback */}
      {positioningFeedback && (
        <div 
          className="positioning-feedback"
          role="status"
          aria-live="polite"
        >
          <span className="feedback-icon" aria-hidden="true">
            {positioningFeedback.status === 'good' ? '✅' : '➡️'}
          </span>
          <span>{positioningFeedback.message}</span>
        </div>
      )}
      
      {/* Challenge indicator */}
      {currentChallenge && (
        <ChallengeIndicator
          challenge={currentChallenge}
          stage={challengeStage}
          language={language}
          reducedMotion={reducedMotion}
        />
      )}
      
      {/* Recording indicator */}
      {isRecording && (
        <div 
          className="recording-indicator"
          role="status"
          aria-live="polite"
          aria-label="Recording in progress"
        >
          <span className="recording-dot" aria-hidden="true" />
          <span>Recording...</span>
        </div>
      )}
    </div>
  );
};