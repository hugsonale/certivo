"""
Async Worker with Multi-Signal Liveness Detection
"""

from fastapi import FastAPI, UploadFile, File, Form, Header, BackgroundTasks
import asyncpg
import os
import sys
import time
import tempfile
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'shared'))

from liveness_detection import MultiSignalLivenessDetector
from audio_visual_sync import AudioVisualSyncDetector
from camera_attestation import CameraAttestationValidator
from far_frr_monitoring import FARFRRMonitor

# ============================================================================
# CONFIGURATION
# ============================================================================

POSTGRES_URL = os.getenv("POSTGRES_URL", "postgresql://certivo:certivo@postgres:5432/certivo")
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")
INTERNAL_AUTH_TOKEN = os.getenv("INTERNAL_AUTH_TOKEN", "secret")

# ============================================================================
# FASTAPI APP
# ============================================================================

app = FastAPI(
    title="Certivo Async Worker - Multi-Signal Liveness",
    version="2.0.0"
)

postgres_pool = None
redis_client = None
liveness_detector = None
av_sync_detector = None
camera_validator = None
far_frr_monitor = None

# ============================================================================
# STARTUP
# ============================================================================

@app.on_event("startup")
async def startup():
    global postgres_pool, redis_client, liveness_detector, av_sync_detector
    global camera_validator, far_frr_monitor
    
    import redis.asyncio as redis
    
    postgres_pool = await asyncpg.create_pool(POSTGRES_URL, min_size=10, max_size=50)
    redis_client = await redis.from_url(REDIS_URL, decode_responses=True)
    
    liveness_detector = MultiSignalLivenessDetector()
    av_sync_detector = AudioVisualSyncDetector()
    camera_validator = CameraAttestationValidator()
    far_frr_monitor = FARFRRMonitor(redis_client, postgres_pool)
    
    print("✅ Async Worker started with multi-signal liveness detection")

@app.on_event("shutdown")
async def shutdown():
    if postgres_pool:
        await postgres_pool.close()
    if redis_client:
        await redis_client.close()

# ============================================================================
# HEALTH CHECK
# ============================================================================

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "async-worker-liveness",
        "timestamp": time.time()
    }

# ============================================================================
# PROCESS VIDEO WITH LIVENESS DETECTION
# ============================================================================

@app.post("/process")
async def process_verification(
    background_tasks: BackgroundTasks,
    video: UploadFile = File(...),
    session_id: str = Form(...),
    challenge_id: str = Form(...),
    device_id: str = Form(...),
    expected_action: str = Form(None),
    audio_challenge: str = Form(None),
    camera_attestation: str = Form(None),
    x_internal_token: str = Header(None)
):
    """
    Process verification with multi-signal liveness detection
    
    Signals:
    1. Motion trajectory consistency
    2. Temporal landmarks
    3. Spoof detection
    4. Action detection
    5. Audio-visual sync (optional)
    6. Camera attestation (optional)
    """
    
    # Auth check
    if x_internal_token != INTERNAL_AUTH_TOKEN:
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    start_time = time.time()
    
    # Save video to temp file
    video_content = await video.read()
    
    with tempfile.NamedTemporaryFile(delete=False, suffix=".webm") as tmp:
        tmp.write(video_content)
        video_path = tmp.name
    
    try:
        # ====================================================================
        # MULTI-SIGNAL LIVENESS ANALYSIS
        # ====================================================================
        
        liveness_result = liveness_detector.analyze_video(
            video_path=video_path,
            expected_action=expected_action,
            audio_challenge=audio_challenge
        )
        
        # ====================================================================
        # AUDIO-VISUAL SYNC (if audio challenge provided)
        # ====================================================================
        
        av_sync_result = None
        if audio_challenge:
            av_sync_result = av_sync_detector.analyze_audio_visual_sync(
                video_path=video_path,
                expected_phrase=audio_challenge
            )
        
        # ====================================================================
        # CAMERA ATTESTATION (if provided)
        # ====================================================================
        
        attestation_result = None
        if camera_attestation:
            import json
            attestation_data = json.loads(camera_attestation)
            
            attestation_result = camera_validator.validate_attestation(
                attestation_data=attestation_data,
                platform=attestation_data.get("platform", "unknown"),
                nonce=challenge_id  # Bind to challenge
            )
        
        # ====================================================================
        # COMBINE SIGNALS FOR FINAL DECISION
        # ====================================================================
        
        final_score = liveness_result["liveness_score"]
        
        # Boost score if audio-visual sync confirmed
        if av_sync_result and av_sync_result.get("is_synced"):
            final_score = min(1.0, final_score * 1.1)
        
        # Boost score if camera attestation valid
        if attestation_result and attestation_result.get("valid"):
            final_score = min(1.0, final_score * 1.1)
        
        # Determine pass/fail
        challenge_passed = final_score > 0.7 and liveness_result.get("is_live", False)
        
        # Check for spoof
        if liveness_result.get("spoof", {}).get("is_spoof", False):
            challenge_passed = False
            final_score = min(final_score, 0.5)
        
        # ====================================================================
        # STORE RESULT IN DATABASE
        # ====================================================================
        
        async with postgres_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO challenge_results
                (session_id, device_id, challenge_id, challenge_passed, liveness_score,
                 frames_analyzed, timestamp_utc)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                """,
                session_id,
                device_id,
                challenge_id,
                challenge_passed,
                final_score,
                liveness_result.get("frame_count", 0),
                datetime.utcnow()
            )
        
        # ====================================================================
        # RECORD FOR FAR/FRR MONITORING
        # ====================================================================
        
        # Note: In production, is_genuine would come from ground truth labels
        # For now, we assume passed challenges are genuine (simplified)
        is_genuine = True  # Would need ground truth in production
        
        await far_frr_monitor.record_verification_outcome(
            session_id=session_id,
            device_id=device_id,
            is_genuine=is_genuine,
            was_accepted=challenge_passed,
            liveness_score=final_score,
            metadata={
                "motion_score": liveness_result.get("motion", {}).get("trajectory_score", 0),
                "temporal_score": liveness_result.get("temporal", {}).get("temporal_score", 0),
                "spoof_score": liveness_result.get("spoof", {}).get("anti_spoof_score", 0)
            }
        )
        
        processing_time = (time.time() - start_time) * 1000
        
        # ====================================================================
        # RETURN COMPREHENSIVE RESULT
        # ====================================================================
        
        return {
            "challenge_passed": challenge_passed,
            "liveness_score": final_score,
            "confidence": liveness_result.get("confidence", 0.0),
            "signals": {
                "motion": liveness_result.get("motion"),
                "temporal": liveness_result.get("temporal"),
                "spoof": liveness_result.get("spoof"),
                "action": liveness_result.get("action"),
                "audio_visual_sync": av_sync_result,
                "camera_attestation": attestation_result
            },
            "processing_time_ms": round(processing_time, 2)
        }
        
    finally:
        # Cleanup temp file
        background_tasks.add_task(os.remove, video_path)

# ============================================================================
# FAR/FRR METRICS ENDPOINT
# ============================================================================

@app.get("/metrics/far-frr")
async def get_far_frr_metrics(
    time_window_hours: int = 24,
    x_internal_token: str = Header(None)
):
    """Get FAR/FRR metrics"""
    
    if x_internal_token != INTERNAL_AUTH_TOKEN:
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    metrics = await far_frr_monitor.calculate_far_frr(time_window_hours)
    
    return metrics

@app.get("/metrics/performance-trend")
async def get_performance_trend(
    days: int = 7,
    x_internal_token: str = Header(None)
):
    """Get performance trend over time"""
    
    if x_internal_token != INTERNAL_AUTH_TOKEN:
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    trend = await far_frr_monitor.get_performance_trend(days)
    
    return trend

@app.get("/metrics/policy-compliance")
async def check_policy_compliance(
    x_internal_token: str = Header(None)
):
    """Check FAR/FRR policy compliance"""
    
    if x_internal_token != INTERNAL_AUTH_TOKEN:
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    compliance = await far_frr_monitor.check_policy_compliance()
    
    return compliance

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8004)