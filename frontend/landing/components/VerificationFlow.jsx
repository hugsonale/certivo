/**
 * Main Verification Flow Component
 * 
 * Features:
 * - Progressive trust (adaptive challenges)
 * - Real-time guidance
 * - Accessibility support
 * - Camera fallback
 * - Performance tracking (<20s target)
 */

import React, { useState, useEffect, useRef } from 'react';
import { CameraPreview } from './CameraPreview';
import { GuidanceDisplay } from './GuidanceDisplay';
import { ProgressTracker } from './ProgressTracker';
import { FallbackOptions } from './FallbackOptions';
import { AccessibilityControls } from './AccessibilityControls';

export const VerificationFlow = ({
  sessionId,
  riskLevel = 'medium',
  language = 'en',
  onComplete,
  onError
}) => {
  // State management
  const [phase, setPhase] = useState('initial'); // initial, consent, camera_setup, challenge, processing, complete
  const [guidance, setGuidance] = useState(null);
  const [challengeConfig, setChallengeConfig] = useState(null);
  const [progress, setProgress] = useState(0);
  const [cameraAvailable, setCameraAvailable] = useState(true);
  const [needsFallback, setNeedsFallback] = useState(false);
  const [accessibilityConfig, setAccessibilityConfig] = useState({
    screenReader: false,
    highContrast: false,
    reducedMotion: false,
    fontSize: 'normal'
  });
  
  // Performance tracking
  const startTimeRef = useRef(null);
  const performanceRef = useRef({
    sessionStart: null,
    consentShown: null,
    consentGranted: null,
    challengeIssued: null,
    videoUploadStart: null,
    videoUploadComplete: null,
    processingStart: null,
    processingComplete: null,
    resultReturned: null
  });
  
  // Initialize
  useEffect(() => {
    initializeVerification();
  }, []);
  
  const initializeVerification = async () => {
    // Start performance tracking
    startTimeRef.current = Date.now();
    performanceRef.current.sessionStart = new Date().toISOString();
    
    // Track event
    await trackPerformanceEvent('session_start');
    
    // Detect accessibility needs
    await detectAccessibility();
    
    // Check camera availability
    await checkCameraAvailability();
    
    // Get challenge configuration based on risk level
    await fetchChallengeConfig();
    
    // Show initial guidance
    updateGuidance('initial');
  };
  
  const detectAccessibility = async () => {
    // Detect screen reader
    const screenReaderActive = 
      navigator.userAgent.includes('NVDA') ||
      navigator.userAgent.includes('JAWS') ||
      navigator.userAgent.includes('VoiceOver');
    
    // Detect preferences
    const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const prefersHighContrast = window.matchMedia('(prefers-contrast: high)').matches;
    
    setAccessibilityConfig({
      screenReader: screenReaderActive,
      highContrast: prefersHighContrast,
      reducedMotion: prefersReducedMotion,
      fontSize: 'normal'
    });
    
    // Announce to screen reader
    if (screenReaderActive) {
      announceToScreenReader(
        'Verification flow started. This will take about 15 to 20 seconds.',
        'polite'
      );
    }
  };
  
  const checkCameraAvailability = async () => {
    try {
      const devices = await navigator.mediaDevices.enumerateDevices();
      const hasCamera = devices.some(device => device.kind === 'videoinput');
      
      setCameraAvailable(hasCamera);
      
      if (!hasCamera) {
        setNeedsFallback(true);
        updateGuidance('error', { errorCode: 'camera_not_found' });
        
        // Announce to screen reader
        announceToScreenReader(
          'Camera not detected. Alternative verification methods are available.',
          'assertive'
        );
      }
    } catch (error) {
      console.error('Camera check failed:', error);
      setCameraAvailable(false);
      setNeedsFallback(true);
    }
  };
  
  const fetchChallengeConfig = async () => {
    try {
      const response = await fetch('/api/v1/verification/challenge-config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: sessionId,
          risk_level: riskLevel,
          language: language
        })
      });
      
      const config = await response.json();
      setChallengeConfig(config);
      
      // Announce challenge count to screen reader
      if (accessibilityConfig.screenReader) {
        announceToScreenReader(
          `You will complete ${config.challenge_count} verification step${config.challenge_count > 1 ? 's' : ''}.`,
          'polite'
        );
      }
    } catch (error) {
      console.error('Failed to fetch challenge config:', error);
      onError(error);
    }
  };
  
  const updateGuidance = async (newPhase, context = {}) => {
    try {
      const response = await fetch('/api/v1/verification/guidance', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          phase: newPhase,
          language: language,
          context: context
        })
      });
      
      const guidanceData = await response.json();
      setGuidance(guidanceData);
      setPhase(newPhase);
      
      // Announce to screen reader
      if (accessibilityConfig.screenReader && guidanceData.screen_reader_text) {
        announceToScreenReader(guidanceData.screen_reader_text, 'polite');
      }
    } catch (error) {
      console.error('Failed to fetch guidance:', error);
    }
  };
  
  const trackPerformanceEvent = async (event) => {
    const timestamp = new Date().toISOString();
    performanceRef.current[event] = timestamp;
    
    try {
      await fetch('/api/v1/performance/track', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: sessionId,
          event: event,
          timestamp: timestamp
        })
      });
    } catch (error) {
      console.error('Performance tracking failed:', error);
    }
  };
  
  const handleConsentGranted = async () => {
    await trackPerformanceEvent('consent_granted');
    setProgress(25);
    updateGuidance('camera_setup');
    
    // Request camera permission
    try {
      await navigator.mediaDevices.getUserMedia({ video: true });
      updateGuidance('positioning');
    } catch (error) {
      if (error.name === 'NotAllowedError') {
        setNeedsFallback(true);
        updateGuidance('error', { errorCode: 'camera_permission_denied' });
      }
    }
  };
  
  const handleChallengeStart = async () => {
    await trackPerformanceEvent('challenge_issued');
    setProgress(50);
    updateGuidance('challenge');
  };
  
  const handleVideoUpload = async (videoBlob) => {
    await trackPerformanceEvent('video_upload_start');
    setProgress(75);
    
    try {
      const formData = new FormData();
      formData.append('video', videoBlob);
      formData.append('session_id', sessionId);
      
      const response = await fetch('/api/v1/verification/upload', {
        method: 'POST',
        body: formData
      });
      
      await trackPerformanceEvent('video_upload_complete');
      
      if (response.ok) {
        handleProcessing();
      } else {
        throw new Error('Upload failed');
      }
    } catch (error) {
      updateGuidance('error', { errorCode: 'upload_failed' });
      onError(error);
    }
  };
  
  const handleProcessing = async () => {
    await trackPerformanceEvent('processing_start');
    setProgress(90);
    updateGuidance('processing');
    
    // Poll for results
    const pollInterval = setInterval(async () => {
      try {
        const response = await fetch(`/api/v1/verification/result/${sessionId}`);
        const result = await response.json();
        
        if (result.status === 'completed') {
          clearInterval(pollInterval);
          await trackPerformanceEvent('result_returned');
          setProgress(100);
          
          // Calculate total time
          const totalTime = Date.now() - startTimeRef.current;
          const totalSeconds = (totalTime / 1000).toFixed(1);
          
          console.log(`✅ Verification completed in ${totalSeconds}s`);
          
          updateGuidance('complete');
          onComplete(result);
        }
      } catch (error) {
        clearInterval(pollInterval);
        onError(error);
      }
    }, 1000);
  };
  
  const announceToScreenReader = (message, priority = 'polite') => {
    const announcement = document.getElementById('sr-announcements');
    if (announcement) {
      announcement.setAttribute('aria-live', priority);
      announcement.textContent = message;
      
      // Clear after announcement
      setTimeout(() => {
        announcement.textContent = '';
      }, 1000);
    }
  };
  
  // Show fallback if camera unavailable
  if (needsFallback) {
    return (
      <FallbackOptions
        reason={cameraAvailable ? 'camera_permission_denied' : 'camera_not_found'}
        language={language}
        onSelectMethod={(method) => {
          console.log('Fallback method selected:', method);
          // Handle fallback method
        }}
      />
    );
  }
  
  return (
    <div 
      className={`verification-flow ${accessibilityConfig.highContrast ? 'high-contrast' : ''}`}
      style={{
        fontSize: accessibilityConfig.fontSize === 'large' ? '18px' : '16px'
      }}
    >
      {/* Screen reader announcements */}
      <div 
        id="sr-announcements" 
        className="sr-only" 
        role="status" 
        aria-live="polite" 
        aria-atomic="true"
      />
      
      {/* Accessibility controls */}
      <AccessibilityControls
        config={accessibilityConfig}
        onChange={setAccessibilityConfig}
      />
      
      {/* Progress tracker */}
      <ProgressTracker
        progress={progress}
        phase={phase}
        language={language}
        ariaLabel={`Verification progress: ${progress}%`}
      />
      
      {/* Guidance display */}
      <GuidanceDisplay
        guidance={guidance}
        language={language}
        reducedMotion={accessibilityConfig.reducedMotion}
      />
      
      {/* Main content */}
      {phase === 'initial' && (
        <div className="initial-screen" role="region" aria-label="Welcome screen">
          <h1>{guidance?.message || 'Welcome to Verification'}</h1>
          <p>{guidance?.instruction}</p>
          <button
            onClick={() => {
              trackPerformanceEvent('consent_shown');
              updateGuidance('consent');
            }}
            className="btn-primary"
            aria-label="Start verification process"
          >
            Start Verification
          </button>
        </div>
      )}
      
      {phase === 'consent' && (
        <div className="consent-screen" role="region" aria-label="Privacy consent">
          <h2>{guidance?.message}</h2>
          <div className="consent-text" tabIndex="0">
            {/* Consent text here */}
            <p>We need your permission to use your camera for verification.</p>
            <ul>
              <li>Your video is encrypted and deleted after 90 days</li>
              <li>We only analyze facial movements, not your identity</li>
              <li>You can withdraw consent anytime</li>
            </ul>
          </div>
          <button
            onClick={handleConsentGranted}
            className="btn-primary"
            aria-label="Accept and continue"
          >
            I Agree
          </button>
          <button
            onClick={() => setNeedsFallback(true)}
            className="btn-secondary"
            aria-label="Use alternative verification method"
          >
            Use Alternative Method
          </button>
        </div>
      )}
      
      {(phase === 'camera_setup' || phase === 'positioning' || phase === 'challenge') && (
        <CameraPreview
          sessionId={sessionId}
          challengeConfig={challengeConfig}
          onPositioned={handleChallengeStart}
          onVideoCapture={handleVideoUpload}
          guidance={guidance}
          language={language}
          reducedMotion={accessibilityConfig.reducedMotion}
          onError={(error) => {
            updateGuidance('error', { errorCode: error.code });
          }}
        />
      )}
      
      {phase === 'processing' && (
        <div className="processing-screen" role="region" aria-label="Processing verification">
          <div className="spinner" aria-hidden={!accessibilityConfig.reducedMotion} />
          <p>{guidance?.message || 'Processing your verification...'}</p>
          <p className="sr-only">Please wait while we verify your submission.</p>
        </div>
      )}
      
      {phase === 'complete' && (
        <div className="complete-screen" role="region" aria-label="Verification complete">
          <div className="success-icon" aria-hidden="true">✅</div>
          <h2>Verification Complete!</h2>
          <p>Thank you for completing the verification.</p>
        </div>
      )}
    </div>
  );
};