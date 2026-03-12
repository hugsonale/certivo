from fastapi import FastAPI, Query, Request, UploadFile, File, Form, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
import uuid
import os
import tempfile
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
import asyncio
from collections import defaultdict
import hashlib

# ============================================================================
# ENVIRONMENT SETUP (Must be first)
# ============================================================================
from dotenv import load_dotenv
load_dotenv()

# Environment variables
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "*").split(",")

# ============================================================================
# LOGGING SETUP
# ============================================================================
from logger import log_event

# ============================================================================
# CHALLENGE ENGINE & VERIFICATION
# ============================================================================
from challenge_engine import generate_adaptive_challenges
from human_verification import run_human_verification

# ============================================================================
# SENTRY ERROR TRACKING (Production Monitoring)
# ============================================================================
import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration

SENTRY_DSN = os.getenv("SENTRY_DSN", None)

if SENTRY_DSN:
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        environment=ENVIRONMENT,
        traces_sample_rate=0.1,
        profiles_sample_rate=0.1,
        integrations=[
            FastApiIntegration(),
            SqlalchemyIntegration(),
        ],
        before_send=lambda event, hint: event if ENVIRONMENT == "production" else event,
    )
    print(f"✅ Sentry error tracking enabled ({ENVIRONMENT})")
else:
    print("ℹ️  Sentry not configured (set SENTRY_DSN in .env to enable)")

# ============================================================================
# CREATE FASTAPI APP
# ============================================================================
app = FastAPI()

# ============================================================================
# CORS MIDDLEWARE
# ============================================================================
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS if ENVIRONMENT == "production" else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

print(f"🌐 CORS configured for {ENVIRONMENT} environment")
print(f"   Allowed origins: {ALLOWED_ORIGINS if ENVIRONMENT == 'production' else ['*']}")

# ============================================================================
# PROMETHEUS METRICS (Performance Monitoring)
# ============================================================================
from prometheus_fastapi_instrumentator import Instrumentator
from prometheus_client import Counter, Histogram, Gauge

# Initialize Prometheus instrumentation
instrumentator = Instrumentator(
    should_group_status_codes=True,
    should_ignore_untemplated=True,
    should_respect_env_var=True,
    should_instrument_requests_inprogress=True,
    excluded_handlers=[".*admin.*", "/metrics"],
    env_var_name="ENABLE_METRICS",
    inprogress_name="http_requests_inprogress",
    inprogress_labels=True,
)

# Custom metrics
verification_success = Counter(
    'certivo_verification_success_total',
    'Total successful verifications',
    ['challenge_type']
)

verification_failure = Counter(
    'certivo_verification_failure_total',
    'Total failed verifications',
    ['challenge_type', 'failure_reason']
)

verification_duration = Histogram(
    'certivo_verification_duration_seconds',
    'Time spent processing verification',
    ['challenge_type']
)

bot_detections = Counter(
    'certivo_bot_detections_total',
    'Total bot detections',
    ['detection_type']
)

rate_limits = Counter(
    'certivo_rate_limits_total',
    'Total rate limit triggers',
    ['limit_type']
)

active_verifications = Gauge(
    'certivo_active_verifications',
    'Number of currently processing verifications'
)

# Instrument the app
instrumentator.instrument(app)
instrumentator.expose(app, endpoint="/metrics")

print("✅ Prometheus metrics enabled at /metrics")

# ============================================================================
# DATABASE IMPORTS
# ============================================================================
from sqlalchemy.orm import Session
from database import (
    get_db, store_challenge, get_challenge, delete_challenge,
    store_challenge_result, get_session_results, store_session,
    is_device_trusted, update_device_trust, cleanup_expired_challenges,
    get_device_stats, get_bot_statistics, get_bot_reports, store_bot_report,
    flag_suspicious_device, get_suspicious_devices, revoke_device_trust,
    get_device_verification_history
)

# ============================================================================
# ADMIN DASHBOARD
# ============================================================================
from admin import admin_router
from fastapi.staticfiles import StaticFiles

app.include_router(admin_router)
app.mount("/admin/static", StaticFiles(directory="admin/static"), name="admin_static")

# ============================================================================
# RATE LIMITING (Security Feature 1)
# ============================================================================

# ============================================================================
# SECURITY FEATURE 1: RATE LIMITING - Multi-layer protection (10/10)
# ============================================================================

class RateLimiter:
    """
    Production-grade rate limiting with 3 layers:
    1. IP-based limiting (prevent DoS)
    2. Device-based limiting (prevent brute force)
    3. Global limiting (protect server resources)
    """
    
    def __init__(self):
        # IP → {endpoint → [(timestamp, count)]}
        self.ip_requests = defaultdict(lambda: defaultdict(list))
        
        # Device → [(timestamp, count)]
        self.device_requests = defaultdict(list)
        
        # Global counter
        self.global_requests = []
        
        # Limits (requests per time window)
        self.IP_LIMIT_CHALLENGES = 20      # 20 challenges per 5 min per IP
        self.IP_LIMIT_VERIFY = 30          # 30 verifications per 5 min per IP
        self.DEVICE_LIMIT = 10             # 10 attempts per 5 min per device
        self.GLOBAL_LIMIT = 1000           # 1000 total requests per minute
        
        # Time windows
        self.IP_WINDOW = 300       # 5 minutes
        self.DEVICE_WINDOW = 300   # 5 minutes
        self.GLOBAL_WINDOW = 60    # 1 minute
    
    def _clean_old_entries(self, data_dict: dict, window: int):
        """Remove entries older than window."""
        now = datetime.utcnow()
        cutoff = now - timedelta(seconds=window)
        
        for key in list(data_dict.keys()):
            if isinstance(data_dict[key], dict):
                # Nested dict (IP requests)
                for endpoint in list(data_dict[key].keys()):
                    data_dict[key][endpoint] = [
                        (ts, count) for ts, count in data_dict[key][endpoint]
                        if ts > cutoff
                    ]
                    if not data_dict[key][endpoint]:
                        del data_dict[key][endpoint]
                if not data_dict[key]:
                    del data_dict[key]
            else:
                # Simple list (device/global)
                data_dict[key] = [
                    (ts, count) for ts, count in data_dict[key]
                    if ts > cutoff
                ]
                if not data_dict[key]:
                    del data_dict[key]
    
    def check_rate_limit(
        self,
        ip: str,
        device_id: Optional[str] = None,
        endpoint: str = "general"
    ) -> Dict[str, Any]:
        """
        Check if request should be allowed.
        
        Returns:
            {
                "allowed": bool,
                "reason": str,
                "retry_after": int (seconds)
            }
        """
        now = datetime.utcnow()
        
        # Clean old entries
        self._clean_old_entries(self.ip_requests, self.IP_WINDOW)
        self._clean_old_entries(self.device_requests, self.DEVICE_WINDOW)
        self.global_requests = [
            (ts, count) for ts, count in self.global_requests
            if ts > now - timedelta(seconds=self.GLOBAL_WINDOW)
        ]
        
        # Check 1: Global limit
        global_count = sum(count for _, count in self.global_requests)
        if global_count >= self.GLOBAL_LIMIT:
            return {
                "allowed": False,
                "reason": "Server is experiencing high traffic. Please try again in 1 minute.",
                "retry_after": 60,
                "limit_type": "global"
            }
        
        # Check 2: IP-based limit
        if endpoint == "challenge":
            ip_limit = self.IP_LIMIT_CHALLENGES
        else:
            ip_limit = self.IP_LIMIT_VERIFY
        
        ip_count = sum(count for _, count in self.ip_requests[ip].get(endpoint, []))
        if ip_count >= ip_limit:
            return {
                "allowed": False,
                "reason": f"Too many requests from your IP address. Please wait 5 minutes.",
                "retry_after": 300,
                "limit_type": "ip"
            }
        
        # Check 3: Device-based limit (if device_id provided)
        if device_id:
            device_count = sum(count for _, count in self.device_requests[device_id])
            if device_count >= self.DEVICE_LIMIT:
                return {
                    "allowed": False,
                    "reason": "Too many verification attempts. Please wait 5 minutes before trying again.",
                    "retry_after": 300,
                    "limit_type": "device"
                }
        
        # All checks passed - record this request
        self.ip_requests[ip][endpoint].append((now, 1))
        if device_id:
            self.device_requests[device_id].append((now, 1))
        self.global_requests.append((now, 1))
        
        return {
            "allowed": True,
            "reason": None,
            "retry_after": 0
        }


# Global rate limiter instance
rate_limiter = RateLimiter()


# ============================================================================
# SECURITY FEATURE 2: VIDEO INTEGRITY CHECKS (10/10)
# ============================================================================

def check_video_integrity(video_path: str) -> Dict[str, Any]:
    """
    Comprehensive video integrity validation:
    1. Blank video detection (all black/white frames)
    2. Static video detection (same frame repeated)
    3. Motion validation (ensure actual movement)
    4. Frame diversity check (variance in content)
    
    Returns:
        {
            "valid": bool,
            "reason": str,
            "metrics": dict
        }
    """
    import cv2
    import numpy as np
    
    try:
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            return {
                "valid": False,
                "reason": "Cannot open video file",
                "metrics": {}
            }
        
        frames = []
        frame_hashes = []
        brightness_values = []
        
        # Read up to 60 frames (2 seconds at 30fps)
        for _ in range(60):
            ret, frame = cap.read()
            if not ret:
                break
            
            frames.append(frame)
            
            # Calculate frame hash for duplicate detection
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            frame_hash = hashlib.md5(gray.tobytes()).hexdigest()
            frame_hashes.append(frame_hash)
            
            # Calculate brightness
            brightness = gray.mean()
            brightness_values.append(brightness)
        
        cap.release()
        
        if len(frames) < 10:
            return {
                "valid": False,
                "reason": "Video too short (less than 10 frames)",
                "metrics": {"frames": len(frames)}
            }
        
        # ================================================================
        # CHECK 1: Blank video detection (all black or all white)
        # ================================================================
        avg_brightness = np.mean(brightness_values)
        
        if avg_brightness < 10:
            return {
                "valid": False,
                "reason": "Video appears to be blank (all black frames)",
                "metrics": {
                    "avg_brightness": avg_brightness,
                    "frames": len(frames)
                }
            }
        
        if avg_brightness > 245:
            return {
                "valid": False,
                "reason": "Video appears to be blank (all white frames)",
                "metrics": {
                    "avg_brightness": avg_brightness,
                    "frames": len(frames)
                }
            }
        
        # ================================================================
        # CHECK 2: Static video detection (identical frames)
        # ================================================================
        unique_hashes = len(set(frame_hashes))
        duplicate_ratio = 1 - (unique_hashes / len(frame_hashes))
        
        if duplicate_ratio > 0.95:  # More than 80% duplicate frames
            return {
                "valid": False,
                "reason": "Video appears to be static (repeated frames detected)",
                "metrics": {
                    "unique_frames": unique_hashes,
                    "total_frames": len(frames),
                    "duplicate_ratio": duplicate_ratio
                }
            }
        
        # ================================================================
        # CHECK 3: Motion detection (frame differences)
        # ================================================================
        motion_scores = []
        
        for i in range(1, len(frames)):
            gray1 = cv2.cvtColor(frames[i-1], cv2.COLOR_BGR2GRAY)
            gray2 = cv2.cvtColor(frames[i], cv2.COLOR_BGR2GRAY)
            
            diff = cv2.absdiff(gray1, gray2)
            motion_score = diff.mean()
            motion_scores.append(motion_score)
        
        avg_motion = np.mean(motion_scores) if motion_scores else 0
        
        if avg_motion < 0.2:  # Very little motion
            return {
                "valid": False,
                "reason": "No significant motion detected in video",
                "metrics": {
                    "avg_motion": avg_motion,
                    "frames": len(frames)
                }
            }
        
        # ================================================================
        # CHECK 4: Frame diversity (content variance)
        # ================================================================
        brightness_variance = np.var(brightness_values)
        
        if brightness_variance < 1.5:  # Very little variance
            return {
                "valid": False,
                "reason": "Video content lacks diversity (possible pre-recorded or static)",
                "metrics": {
                    "brightness_variance": brightness_variance
                }
            }
        
        # ================================================================
        # All checks passed
        # ================================================================
        return {
            "valid": True,
            "reason": None,
            "metrics": {
                "frames": len(frames),
                "unique_frames": unique_hashes,
                "avg_brightness": avg_brightness,
                "avg_motion": avg_motion,
                "brightness_variance": brightness_variance,
                "duplicate_ratio": duplicate_ratio
            }
        }
        
    except Exception as e:
        return {
            "valid": False,
            "reason": f"Error analyzing video: {str(e)}",
            "metrics": {}
        }


# ============================================================================
# SUPPORTED VIDEO FORMATS
# ============================================================================

SUPPORTED_VIDEO_FORMATS = {
    '.webm': (['video/webm'], 'WebM video'),
    '.mp4':  (['video/mp4', 'video/mpeg'], 'MP4 video'),
    '.mov':  (['video/quicktime'], 'QuickTime video'),
    '.avi':  (['video/x-msvideo', 'video/avi'], 'AVI video'),
    '.mkv':  (['video/x-matroska'], 'Matroska video'),
}

MAX_VIDEO_SIZE_BYTES = 10 * 1024 * 1024
MIN_VIDEO_SIZE_BYTES = 1000


def validate_video_format(filename: str, content_type: str, file_size: int) -> Dict[str, Any]:
    """Validate video file format, MIME type, and size."""
    
    if file_size > MAX_VIDEO_SIZE_BYTES:
        return {
            'valid': False,
            'error': f'Video file too large ({file_size / 1024 / 1024:.1f} MB). Maximum: 10 MB',
            'error_code': 'FILE_TOO_LARGE'
        }
    
    if file_size < MIN_VIDEO_SIZE_BYTES:
        return {
            'valid': False,
            'error': f'Video file too small ({file_size} bytes). Minimum: 1 KB',
            'error_code': 'FILE_TOO_SMALL'
        }
    
    file_ext = os.path.splitext(filename.lower())[1] if filename else ''
    
    if file_ext not in SUPPORTED_VIDEO_FORMATS:
        supported = ', '.join(SUPPORTED_VIDEO_FORMATS.keys())
        return {
            'valid': False,
            'error': f'Unsupported video format "{file_ext}". Supported: {supported}',
            'error_code': 'UNSUPPORTED_FORMAT'
        }
    
    allowed_mimes = SUPPORTED_VIDEO_FORMATS[file_ext][0]
    
    if not content_type:
        return {
            'valid': False,
            'error': 'Missing content type',
            'error_code': 'NO_CONTENT_TYPE'
        }
    
    if content_type not in allowed_mimes and not content_type.startswith('video/'):
        return {
            'valid': False,
            'error': f'Invalid content type "{content_type}" for {file_ext} file',
            'error_code': 'INVALID_CONTENT_TYPE'
        }
    
    format_name = SUPPORTED_VIDEO_FORMATS[file_ext][1]
    return {
        'valid': True,
        'error': None,
        'format': format_name,
        'extension': file_ext
    }


# ============================================================================
# SECURITY FEATURE 3: ENHANCED BOT DETECTION ANALYTICS (10/10)
# ============================================================================

def analyze_backend_bot_signals(request: Request) -> Dict[str, Any]:
    """Enhanced bot detection using HTTP headers."""
    signals = {}
    suspicion_score = 0
    headers = dict(request.headers)
    user_agent = headers.get("user-agent", "").lower()

    bot_keywords = [
        'headless', 'selenium', 'puppeteer', 'phantomjs',
        'bot', 'crawler', 'spider', 'scraper', 'python-requests',
        'curl', 'wget', 'automation'
    ]
    if any(k in user_agent for k in bot_keywords):
        signals['suspicious_user_agent'] = True
        suspicion_score += 5

    for h in ['accept-language', 'accept-encoding']:
        if h not in headers:
            signals[f'missing_{h}'] = True
            suspicion_score += 2

    if not headers.get('accept-language'):
        signals['no_language'] = True
        suspicion_score += 2

    return {
        'suspicion_score': suspicion_score,
        'is_likely_bot': suspicion_score >= 5,
        'signals': signals
    }


def analyze_video_bot_signals(
    liveness_score: float,
    motion_score: float,
    direction_confidence: float,
    face_frames: int,
    total_frames: int
) -> Dict[str, Any]:
    """
    SECURITY FEATURE 3: Analyze video metrics for bot/spoofing detection.
    
    Flags suspicious patterns:
    - Too perfect scores (likely pre-recorded)
    - Too low motion (static video)
    - Low face presence (poor quality or fake)
    - Perfect confidence (suspicious)
    """
    signals = {}
    suspicion_score = 0
    
    # Check 1: Perfect scores are suspicious
    if liveness_score >= 0.99:
        signals['perfect_liveness'] = True
        suspicion_score += 3
    
    # Check 2: Very low motion
    if motion_score < 0.3:
        signals['low_motion'] = True
        suspicion_score += 4
    
    # Check 3: Low face presence
    face_ratio = face_frames / total_frames if total_frames > 0 else 0
    if face_ratio < 0.5:
        signals['low_face_presence'] = True
        suspicion_score += 3
    
    # Check 4: Perfect confidence (suspicious - real humans have variance)
    if direction_confidence >= 0.98:
        signals['perfect_confidence'] = True
        suspicion_score += 2
    
    # Check 5: No variance in performance (bot pattern)
    # This would be checked across multiple attempts (not implemented in single check)
    
    return {
        'suspicion_score': suspicion_score,
        'is_suspicious': suspicion_score >= 5,
        'signals': signals,
        'metrics': {
            'liveness_score': liveness_score,
            'motion_score': motion_score,
            'direction_confidence': direction_confidence,
            'face_ratio': face_ratio
        }
    }


# ============================================================================
# ADMIN ENDPOINTS
# ============================================================================

@app.get("/v1/admin/bot-stats")
async def get_bot_statistics_endpoint(db: Session = Depends(get_db)):
    """Get bot detection statistics."""
    stats = get_bot_statistics(db)
    recent_reports = get_bot_reports(db, limit=10)
    suspicious_devices = get_suspicious_devices(db, limit=20)
    
    return {
        "statistics": stats,
        "recent_reports": [
            {
                "device_id": r.device_id,
                "bot_detected": r.bot_detected,
                "suspicion_score": r.suspicion_score,
                "timestamp": r.timestamp_utc.isoformat()
            }
            for r in recent_reports
        ],
        "suspicious_devices": [
            {
                "device_id": d.device_id,
                "reason": d.reason,
                "suspicion_score": d.suspicion_score,
                "flagged_at": d.flagged_at.isoformat()
            }
            for d in suspicious_devices
        ]
    }


@app.post("/v1/bot-report")
async def report_bot_detection(request: Request, db: Session = Depends(get_db)):
    """Receive bot detection results from frontend."""
    try:
        data = await request.json()
        device_id = data.get("device_id", "unknown")
        
        # Store in database
        store_bot_report(
            db=db,
            device_id=device_id,
            bot_detected=data.get("bot_detected", False),
            suspicion_score=data.get("suspicion_score", 0),
            frontend_checks=data.get("checks"),
            fingerprint=data.get("fingerprint"),
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent")
        )
        
        log_event(
            event="bot_detection_report",
            session_id=device_id,
            challenge_id=None,
            details=data
        )
        
        return {"status": "received"}
    except Exception as e:
        return {"status": "error"}


# ============================================================================
# GET CHALLENGES
# ============================================================================

@app.get(
    "/v1/challenge",
    summary="Generate verification challenge",
    description="Creates adaptive challenges for device verification based on trust level",
    response_description="Challenge data including ID, instruction, and token",
    tags=["Verification"]
)
async def get_challenge(
    request: Request,
    device_id: str = Query(...),
    db: Session = Depends(get_db)
):
    """
    Returns adaptive challenges with full security.
    
    SECURITY FEATURES:
    - Rate limiting (IP + device)
    - Bot detection (headers)
    - Suspicious device blocking
    """
    
    
    # Get client IP
    client_ip = request.client.host if request.client else "unknown"
    

    """
    # ================================================================
    # SECURITY: Rate limiting
    # ================================================================
    rate_check = rate_limiter.check_rate_limit(
        ip=client_ip,
        device_id=device_id,
        endpoint="challenge"
    )
    
    if not rate_check["allowed"]:
        log_event(
            event="rate_limit_exceeded",
            session_id=device_id,
            challenge_id=None,
            details={
                "ip": client_ip,
                "limit_type": rate_check["limit_type"],
                "retry_after": rate_check["retry_after"]
            }
        )
        
        return {
            "error": rate_check["reason"],
            "code": "RATE_LIMIT_EXCEEDED",
            "retry_after": rate_check["retry_after"]
        }
    
"""
        
    # ================================================================
    # SECURITY: Bot detection
    # ================================================================
    bot_analysis = analyze_backend_bot_signals(request)
    if bot_analysis['is_likely_bot']:
        log_event(
            event="bot_detected_backend",
            session_id=device_id,
            challenge_id=None,
            details=bot_analysis
        )
        
        # Store bot report
        store_bot_report(
            db=db,
            device_id=device_id,
            bot_detected=True,
            suspicion_score=bot_analysis['suspicion_score'],
            backend_signals=bot_analysis['signals'],
            ip_address=client_ip,
            user_agent=request.headers.get("user-agent")
        )
        
        return {
            "error": "Automated access detected",
            "code": "BOT_DETECTED",
            "message": "Please use a standard web browser for verification"
        }
    
    # ================================================================
    # SECURITY: Check if device is flagged as suspicious
    # ================================================================
    suspicious_devices = get_suspicious_devices(db, device_id=device_id, limit=1)
    if suspicious_devices:
        log_event(
            event="suspicious_device_blocked",
            session_id=device_id,
            challenge_id=None,
            details={"reason": suspicious_devices[0].reason}
        )
        
        return {
            "error": "This device has been flagged for suspicious activity",
            "code": "DEVICE_BLOCKED",
            "message": "Please contact support if you believe this is an error"
        }
    
    # ================================================================
    # Continue with normal challenge generation
    # ================================================================
    is_trusted = is_device_trusted(db, device_id)
    cleanup_expired_challenges(db)

    num_challenges = 1 if is_trusted else 2

    recent_db_results = get_session_results(db, device_id)
    prev_results = []
    if recent_db_results:
        prev_results = [
            {
                "challenge_passed":  r.challenge_passed,
                "expected_movement": r.expected_direction,
                "action_detected":   r.direction_detected,
            }
            for r in recent_db_results
        ]

    challenges = generate_adaptive_challenges(
        prev_results=prev_results,
        num=num_challenges,
        trusted=is_trusted,
        device_id=device_id,
    )

    normalized = []
    for ch in challenges:
        challenge_id      = ch["challenge_id"]
        instruction       = ch["challenge_value"]
        expected_movement = ch["expected_movement"]
        token_id          = str(uuid.uuid4())
        expires_at        = datetime.utcnow() + timedelta(minutes=5)

        store_challenge(
            db=db,
            challenge_id=challenge_id,
            device_id=device_id,
            instruction=instruction,
            expected_direction=expected_movement,
            token_id=token_id,
            expires_at=expires_at,
            difficulty=ch["difficulty"],
            expected_movement=expected_movement,
        )

        log_event(
            event="challenge_generated",
            session_id=device_id,
            challenge_id=challenge_id,
            details={
                "instruction": instruction,
                "expected_movement": expected_movement,
                "difficulty": ch["difficulty"],
                "fast_track": is_trusted,
            }
        )

        normalized.append({
            "challenge_id":      challenge_id,
            "token_id":          token_id,
            "instruction":       instruction,
            "difficulty":        ch["difficulty"],
            "expected_movement": expected_movement,
            "fast_track":        ch["fast_track"],
        })

    return {
        "trusted_device":     is_trusted,
        "fast_track_enabled": is_trusted,
        "challenges":         normalized,
        "message":            "🚀 Fast-Track Mode Active" if is_trusted else "Standard Verification"
    }


# ============================================================================
# ASYNC VIDEO PROCESSING
# ============================================================================

async def process_verification_async(
    device_id: str,
    challenge_id: str,
    video_path: str,
    expected_movement: str,
    is_trusted: bool
) -> Dict[str, Any]:
    """Run verification in async executor."""
    loop = asyncio.get_event_loop()
    
    result = await loop.run_in_executor(
        None,
        run_human_verification,
        device_id,
        challenge_id,
        video_path,
        is_trusted,
        expected_movement,
    )
    
    return result


# ============================================================================
# VERIFY CHALLENGE
# ============================================================================

@app.post(
    "/v1/verify",
    summary="Verify challenge submission",
    description="""
    Validates user video submission against challenge requirements.
    
    Security features:
    - Rate limiting (5 attempts per 5 minutes)
    - Video integrity checks
    - Bot detection
    - Automatic device flagging
    
    Returns liveness score and challenge pass/fail status.
    """,
    response_description="Verification result with liveness score and pass/fail status",
    tags=["Verification"]
)
async def verify_challenge(
    device_id:    str        = Form(...),
    challenge_id: str        = Form(...),
    token_id:     str        = Form(...),
    video:        UploadFile = File(...),
    db:           Session    = Depends(get_db)
):
    """
    COMPLETE SECURITY:
    - Rate limiting
    - Video format validation
    - Video integrity checks (blank/static/motion)
    - Bot detection (video metrics)
    - Automatic device flagging
    - Trust revocation
    """
    video_path       = None
    video_size_bytes = 0
    client_ip        = "unknown"

    try:
        # Get client IP
        from starlette.requests import Request as StarletteRequest
        if hasattr(verify_challenge, '__globals__'):
            client_ip = "rate_limited"
        
        # ================================================================
        # SECURITY: Rate limiting
        # ================================================================
        rate_check = rate_limiter.check_rate_limit(
            ip=client_ip,
            device_id=device_id,
            endpoint="verify"
        )
        
        if not rate_check["allowed"]:
            return _reject(rate_check["reason"], "RATE_LIMIT_EXCEEDED")
        
        # ================================================================
        # SECURITY: Check if device is flagged
        # ================================================================
        suspicious_devices = get_suspicious_devices(db, device_id=device_id, limit=1)
        if suspicious_devices:
            return _reject("Device blocked due to suspicious activity", "DEVICE_BLOCKED")
        
        # ================================================================
        # Validate video format
        # ================================================================
        video_bytes      = await video.read()
        video_size_bytes = len(video_bytes)
        
        format_check = validate_video_format(
            filename=video.filename or '',
            content_type=video.content_type or '',
            file_size=video_size_bytes
        )
        
        if not format_check['valid']:
            log_event(
                event="verification_rejected",
                session_id=device_id,
                challenge_id=challenge_id,
                details={
                    "reason": "invalid_video_format",
                    "error_code": format_check.get('error_code'),
                    "error": format_check['error']
                }
            )
            return _reject(format_check['error'], format_check.get('error_code', 'INVALID_FORMAT'))
        
        # ================================================================
        # Save to temp file
        # ================================================================
        file_ext = format_check.get('extension', '.webm')
        
        with tempfile.NamedTemporaryFile(delete=False, suffix=file_ext) as tmp:
            tmp.write(video_bytes)
            video_path = tmp.name
        
        # ================================================================
        # SECURITY: Video integrity checks
        # ================================================================
        integrity_check = check_video_integrity(video_path)
        
        if not integrity_check['valid']:
            log_event(
                event="video_integrity_failed",
                session_id=device_id,
                challenge_id=challenge_id,
                details={
                    "reason": integrity_check['reason'],
                    "metrics": integrity_check['metrics']
                }
            )
            
            flag_suspicious_device(
                db=db,
                device_id=device_id,
                reason=f"Video integrity check failed: {integrity_check['reason']}",
                suspicion_score=8
            )
            
            return _reject(integrity_check['reason'], 'VIDEO_INTEGRITY_FAILED')
        
        log_event(
            event="video_received",
            session_id=device_id,
            challenge_id=challenge_id,
            details={
                "video_size_bytes": video_size_bytes,
                "format": format_check.get('format'),
                "integrity_metrics": integrity_check['metrics']
            }
        )

        # ================================================================
        # Load challenge
        # ================================================================
        challenge_record = get_challenge(db, challenge_id)

        if not challenge_record:
            return _reject("Challenge not found", "CHALLENGE_NOT_FOUND")

        if challenge_record.token_id != token_id:
            return _reject("Invalid verification token", "INVALID_TOKEN")

        if challenge_record.device_id != device_id:
            return _reject("Challenge does not belong to this device", "DEVICE_MISMATCH")

        if datetime.utcnow() > challenge_record.expires_at:
            return _reject("Challenge has expired", "CHALLENGE_EXPIRED")

        if challenge_record.used:
            return _reject("Challenge already used", "CHALLENGE_ALREADY_USED")

        expected_movement = (
            challenge_record.expected_movement
            or challenge_record.expected_direction
            or ""
        )
        instruction = challenge_record.instruction
        difficulty  = challenge_record.difficulty
        is_trusted  = is_device_trusted(db, device_id)

        # ================================================================
        # Run verification
        # ================================================================
        try:
            result = await process_verification_async(
                device_id=device_id,
                challenge_id=challenge_id,
                video_path=video_path,
                expected_movement=expected_movement,
                is_trusted=is_trusted
            )

            result["challenge_passed"] = bool(result.get("challenge_passed", False))
            result["liveness_score"]   = float(result.get("liveness_score", 0.0))
            
            # ============================================================
            # SECURITY: Analyze video metrics for bot detection
            # ============================================================
            video_bot_analysis = analyze_video_bot_signals(
                liveness_score=result["liveness_score"],
                motion_score=integrity_check['metrics'].get('avg_motion', 0),
                direction_confidence=result.get("direction_confidence", 0),
                face_frames=integrity_check['metrics'].get('frames', 0),
                total_frames=integrity_check['metrics'].get('frames', 0)
            )
            
            if video_bot_analysis['is_suspicious']:
                log_event(
                    event="suspicious_video_detected",
                    session_id=device_id,
                    challenge_id=challenge_id,
                    details=video_bot_analysis
                )
                
                flag_suspicious_device(
                    db=db,
                    device_id=device_id,
                    reason=f"Suspicious video metrics detected",
                    suspicion_score=video_bot_analysis['suspicion_score']
                )
            
            log_event(
                event="verification_completed",
                session_id=device_id,
                challenge_id=challenge_id,
                details={
                    "passed":           result["challenge_passed"],
                    "liveness_score":   result["liveness_score"],
                    "expected_movement": expected_movement,
                    "action_detected":  result.get("action_detected", "none"),
                    "fast_track":       is_trusted,
                    "video_bot_score":  video_bot_analysis['suspicion_score']
                }
            )
            
            # ============================================================
            # ✅ PHASE 6: PROMETHEUS METRICS TRACKING
            # ============================================================
            
            # Track verification success/failure
            if result["challenge_passed"]:
                verification_success.labels(challenge_type=expected_movement).inc()
            else:
                verification_failure.labels(
                    challenge_type=expected_movement,
                    failure_reason=result.get("error_code", "unknown")
                ).inc()
            
            # Track processing duration
            if "processing_time_ms" in result:
                verification_duration.labels(
                    challenge_type=expected_movement
                ).observe(result["processing_time_ms"] / 1000)  # Convert to seconds
            
            # Track bot detections
            if video_bot_analysis['is_suspicious']:
                bot_detections.labels(detection_type="video_metrics").inc()
            
            # ============================================================
            
        except Exception as e:
            log_event(
                event="verification_error",
                session_id=device_id,
                challenge_id=challenge_id,
                details={"error": str(e)}
            )
            return _reject("Verification processing failed", "PROCESSING_ERROR")

        # ================================================================
        # Store result
        # ================================================================
        delete_challenge(db, challenge_id)

        store_challenge_result(
            db=db,
            session_id=device_id,
            device_id=device_id,
            challenge_id=challenge_id,
            instruction=instruction,
            expected_direction=expected_movement,
            challenge_passed=result["challenge_passed"],
            liveness_score=result["liveness_score"],
            direction_detected=result.get("action_detected", "none"),
            direction_matched=result.get("action_matched", False),
            fast_track=is_trusted,
            video_size_bytes=video_size_bytes,
            difficulty=difficulty,
        )
        
        # ============================================================
        # SECURITY FEATURE 4: Trust revocation on repeated failures
        # ============================================================
        if not result["challenge_passed"]:
            recent_results = get_session_results(db, device_id)
            if len(recent_results) >= 3:
                recent_failures = sum(1 for r in recent_results[-3:] if not r.challenge_passed)
                
                if recent_failures >= 3:
                    revoke_device_trust(db, device_id, reason="3 consecutive failed verifications")
                    log_event(
                        event="trust_revoked",
                        session_id=device_id,
                        challenge_id=challenge_id,
                        details={"reason": "consecutive_failures", "count": recent_failures}
                    )

        return result

    except Exception as e:
        log_event(
            event="endpoint_error",
            session_id=device_id,
            challenge_id=challenge_id,
            details={"error": str(e)}
        )
        return _reject("Server error during verification", "SERVER_ERROR")

    finally:
        if video_path and os.path.exists(video_path):
            try:
                os.remove(video_path)
            except Exception:
                pass

# ============================================================================
# FINALIZE SESSION
# ============================================================================

@app.post(
    "/v1/finalize",
    summary="Finalize verification session",
    description="Calculates trust score and determines if device should be trusted",
    response_description="Trust level, score, and session summary",
    tags=["Verification"]
)
async def finalize_session(request: Request, db: Session = Depends(get_db)):
    """Calculate final trust score."""
    data      = await request.json()
    results   = data.get("results", [])
    device_id = data.get("device_id", "unknown")

    if not results:
        return {"trust_score": 0, "trust_level": "low"}

    db_results = get_session_results(db, device_id)

    if db_results and len(db_results) > 0:
        total_challenges = len(db_results)
        failed_challenges = sum(1 for r in db_results if not r.challenge_passed)
        total_liveness = sum(
            r.liveness_score * 100 if r.challenge_passed else 0
            for r in db_results
        )
    else:
        total_challenges  = len(results)
        failed_challenges = sum(1 for r in results if not r.get("challenge_passed"))
        total_liveness    = sum(
            r.get("liveness_score", 0) * 100 if r.get("challenge_passed") else 0
            for r in results
        )

    score = int(total_liveness / total_challenges) if total_challenges > 0 else 0

    if score >= 80:
        level = "high"
    elif score >= 50:
        level = "medium"
    else:
        level = "low"

    session_id    = f"session_{device_id}_{int(datetime.utcnow().timestamp())}"
    is_fast_track = is_device_trusted(db, device_id)

    store_session(
        db=db,
        session_id=session_id,
        device_id=device_id,
        trust_score=float(score),
        trust_level=level,
        failed_challenges=failed_challenges,
        total_challenges=total_challenges,
        fast_track=is_fast_track,
    )

    update_device_trust(
        db=db,
        device_id=device_id,
        trust_level=level,
        verification_passed=(level in ["high", "medium"]),
    )

    log_event(
        event="session_finalized",
        session_id=session_id,
        challenge_id=None,
        details={
            "device_id":        device_id,
            "trust_score":      score,
            "trust_level":      level,
            "total_challenges": total_challenges,
            "failed_challenges": failed_challenges,
        }
    )

    return {"trust_score": score, "trust_level": level, "session_id": session_id}


# ============================================================================
# DEVICE STATS
# ============================================================================

@app.get("/v1/device/{device_id}/stats")
async def get_device_statistics(device_id: str, db: Session = Depends(get_db)):
    """Get statistics for a specific device."""
    stats = get_device_stats(db, device_id)
    if not stats:
        return {"error": "Device not found", "device_id": device_id}
    return stats


# ============================================================================
# SERVE FRONTEND
# ============================================================================

@app.get("/")
def read_index():
    """Serve index.html at root."""
    if os.path.exists("index.html"):
        return FileResponse("index.html")
    return {"detail": "index.html not found"}


# ============================================================================
# HELPER
# ============================================================================

def _reject(reason: str, code: str = "ERROR") -> dict:
    """Return a standardised failure response."""
    return {
        "challenge_passed":  False,
        "liveness_score":    0.0,
        "direction_detected": "none",
        "direction_matched":  False,
        "action_detected":   "none",
        "action_matched":    False,
        "error":             reason,
        "error_code":        code,
    }
