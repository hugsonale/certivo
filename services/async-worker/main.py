"""
Async Worker Service
- Background video processing
- Queue-based job processing
- Horizontal scaling support
- Long-running tasks
"""

from fastapi import FastAPI, UploadFile, File, Form, Header, HTTPException, BackgroundTasks
from pydantic import BaseModel
import redis.asyncio as redis
import asyncpg
import httpx
import boto3
import cv2
import numpy as np
import tempfile
import os
import json
import time
import uuid
from typing import Dict, Any, Optional
from datetime import datetime

# ============================================================================
# CONFIGURATION
# ============================================================================

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")
POSTGRES_URL = os.getenv("POSTGRES_URL", "postgresql://certivo:certivo@postgres:5432/certivo")
S3_ENDPOINT = os.getenv("S3_ENDPOINT", "http://minio:9000")
S3_ACCESS_KEY = os.getenv("S3_ACCESS_KEY", "minioadmin")
S3_SECRET_KEY = os.getenv("S3_SECRET_KEY", "minioadmin")
S3_BUCKET = os.getenv("S3_BUCKET", "certivo-videos")
INTERNAL_AUTH_TOKEN = os.getenv("INTERNAL_AUTH_TOKEN", "secret")

# ============================================================================
# S3 CLIENT
# ============================================================================

s3_client = boto3.client(
    's3',
    endpoint_url=S3_ENDPOINT,
    aws_access_key_id=S3_ACCESS_KEY,
    aws_secret_access_key=S3_SECRET_KEY
)

# Ensure bucket exists
try:
    s3_client.head_bucket(Bucket=S3_BUCKET)
except:
    s3_client.create_bucket(Bucket=S3_BUCKET)
    print(f"✅ Created S3 bucket: {S3_BUCKET}")

# ============================================================================
# MODELS
# ============================================================================

class ProcessRequest(BaseModel):
    session_id: str
    challenge_id: str
    token_id: str
    device_id: str
    video_key: str
    video_size: int

# ============================================================================
# DATABASE
# ============================================================================

postgres_pool = None

async def get_postgres():
    global postgres_pool
    if postgres_pool is None:
        postgres_pool = await asyncpg.create_pool(
            POSTGRES_URL,
            min_size=10,
            max_size=50,
            command_timeout=60
        )
    return postgres_pool

# ============================================================================
# FASTAPI APP
# ============================================================================

app = FastAPI(
    title="Certivo Async Worker",
    description="Background processing service",
    version="1.0.0"
)

# ============================================================================
# HEALTH CHECK
# ============================================================================

@app.get("/health")
async def health_check():
    """Worker health check"""
    pg_pool = await get_postgres()
    
    try:
        async with pg_pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        postgres_status = "healthy"
    except Exception as e:
        postgres_status = f"unhealthy: {str(e)}"
    
    # Check S3
    try:
        s3_client.head_bucket(Bucket=S3_BUCKET)
        s3_status = "healthy"
    except Exception as e:
        s3_status = f"unhealthy: {str(e)}"
    
    return {
        "status": "healthy",
        "service": "async-worker",
        "postgres": postgres_status,
        "s3": s3_status,
        "timestamp": time.time()
    }

# ============================================================================
# VIDEO PROCESSING
# ============================================================================

async def process_video_task(
    video_path: str,
    session_id: str,
    challenge_id: str,
    device_id: str
) -> Dict[str, Any]:
    """
    Process video for liveness detection
    This is where your human_verification.py logic goes
    """
    
    try:
        # Open video
        cap = cv2.VideoCapture(video_path)
        
        if not cap.isOpened():
            return {
                "challenge_passed": False,
                "confidence": 0,
                "error": "Cannot open video file"
            }
        
        frames = []
        frame_count = 0
        
        while len(frames) < 30 and frame_count < 100:
            ret, frame = cap.read()
            if not ret:
                break
            frames.append(frame)
            frame_count += 1
        
        cap.release()
        
        if len(frames) < 5:
            return {
                "challenge_passed": False,
                "confidence": 0,
                "error": "Video too short"
            }
        
        # Basic liveness detection (placeholder - use your actual logic)
        # Calculate motion score
        motion_scores = []
        for i in range(1, len(frames)):
            diff = cv2.absdiff(frames[i-1], frames[i])
            motion_score = diff.mean()
            motion_scores.append(motion_score)
        
        avg_motion = np.mean(motion_scores) if motion_scores else 0
        
        # Simple scoring
        liveness_score = min(1.0, avg_motion / 10.0)
        challenge_passed = liveness_score > 0.3
        
        return {
            "challenge_passed": challenge_passed,
            "liveness_score": float(liveness_score),
            "confidence": 0.85 if challenge_passed else 0.4,
            "frames_analyzed": len(frames),
            "avg_motion": float(avg_motion)
        }
        
    except Exception as e:
        return {
            "challenge_passed": False,
            "confidence": 0,
            "error": str(e)
        }

# ============================================================================
# PROCESS ENDPOINT
# ============================================================================

@app.post("/process")
async def process_verification(
    background_tasks: BackgroundTasks,
    video: UploadFile = File(...),
    session_id: str = Form(...),
    challenge_id: str = Form(...),
    token_id: str = Form(...),
    device_id: str = Form(...),
    x_internal_token: str = Header(None)
):
    """Process verification video asynchronously"""
    
    # Auth check
    if x_internal_token != INTERNAL_AUTH_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    start_time = time.time()
    
    # Save video to temp file
    video_content = await video.read()
    
    with tempfile.NamedTemporaryFile(delete=False, suffix=".webm") as tmp:
        tmp.write(video_content)
        video_path = tmp.name
    
    try:
        # Upload to S3 (async in background)
        s3_key = f"{device_id}/{session_id}/{video.filename}"
        background_tasks.add_task(
            s3_client.upload_fileobj,
            open(video_path, 'rb'),
            S3_BUCKET,
            s3_key
        )
        
        # Process video
        result = await process_video_task(
            video_path=video_path,
            session_id=session_id,
            challenge_id=challenge_id,
            device_id=device_id
        )
        
        # Store result in database
        pg_pool = await get_postgres()
        async with pg_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO challenge_results
                (session_id, device_id, challenge_id, challenge_passed, liveness_score, 
                 video_size_bytes, frames_analyzed, timestamp_utc)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                """,
                session_id,
                device_id,
                challenge_id,
                result.get("challenge_passed", False),
                result.get("liveness_score", 0),
                len(video_content),
                result.get("frames_analyzed", 0),
                datetime.utcnow()
            )
        
        processing_time = (time.time() - start_time) * 1000  # ms
        
        return {
            **result,
            "session_id": session_id,
            "s3_key": s3_key,
            "processing_time_ms": round(processing_time, 2)
        }
        
    finally:
        # Cleanup temp file
        if os.path.exists(video_path):
            background_tasks.add_task(os.remove, video_path)

# ============================================================================
# STARTUP/SHUTDOWN
# ============================================================================

@app.on_event("startup")
async def startup():
    global postgres_pool
    postgres_pool = await asyncpg.create_pool(
        POSTGRES_URL,
        min_size=10,
        max_size=50
    )
    print("✅ Async Worker started")

@app.on_event("shutdown")
async def shutdown():
    if postgres_pool:
        await postgres_pool.close()
    print("🛑 Async Worker shutdown")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8004)