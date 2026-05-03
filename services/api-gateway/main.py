"""
API Gateway with Request Validation
"""

from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Form
from fastapi.responses import JSONResponse
from pydantic import ValidationError
import httpx
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'shared'))

from request_validation import (
    ChallengeRequest,
    VerifyRequest,
    FinalizeRequest,
    AdminRevokeRequest,
    validate_request
)
from file_upload_validation import FileUploadValidator
from error_codes import ErrorCode, ValidationError as CustomValidationError

# ============================================================================
# CONFIGURATION
# ============================================================================

CHALLENGE_SERVICE_URL = os.getenv("CHALLENGE_SERVICE_URL", "http://challenge-service:8002")
VERIFICATION_SERVICE_URL = os.getenv("VERIFICATION_SERVICE_URL", "http://verification-api:8003")
INTERNAL_AUTH_TOKEN = os.getenv("INTERNAL_AUTH_TOKEN", "secret")

# ============================================================================
# FASTAPI APP
# ============================================================================

app = FastAPI(
    title="Certivo API Gateway - Hardened",
    version="2.0.0"
)

file_validator = FileUploadValidator()

# ============================================================================
# MIDDLEWARE - REQUEST SIZE LIMIT
# ============================================================================

@app.middleware("http")
async def limit_upload_size(request: Request, call_next):
    """Limit request body size"""
    
    # Skip for non-upload endpoints
    if request.url.path != "/v1/verify":
        return await call_next(request)
    
    # Check Content-Length header
    content_length = request.headers.get("content-length")
    
    if content_length:
        content_length = int(content_length)
        
        # 55MB max (50MB video + 5MB overhead)
        if content_length > 55 * 1024 * 1024:
            return JSONResponse(
                status_code=413,
                content={
                    "error": "Request too large",
                    "error_code": "REQUEST_TOO_LARGE",
                    "max_size_bytes": 55 * 1024 * 1024
                }
            )
    
    return await call_next(request)

# ============================================================================
# ERROR HANDLERS
# ============================================================================

@app.exception_handler(ValidationError)
async def validation_exception_handler(request: Request, exc: ValidationError):
    """Handle Pydantic validation errors"""
    
    return JSONResponse(
        status_code=422,
        content={
            "error": "Validation failed",
            "error_code": "VALIDATION_ERROR",
            "details": exc.errors()
        }
    )

@app.exception_handler(CustomValidationError)
async def custom_validation_handler(request: Request, exc: CustomValidationError):
    """Handle custom validation errors"""
    
    return JSONResponse(
        status_code=exc.status_code,
        content=exc.to_dict()
    )

# ============================================================================
# HEALTH CHECK
# ============================================================================

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "api-gateway-hardened",
        "timestamp": time.time()
    }

# ============================================================================
# CHALLENGE ENDPOINT (WITH VALIDATION)
# ============================================================================

@app.post("/v1/challenge")
async def create_challenge(request: Request):
    """
    Create verification challenge with strict validation
    
    Validation:
    - Device ID format and SQL injection prevention
    - Trust level enum validation
    - Client metadata size and structure validation
    """
    
    # Parse request body
    try:
        body = await request.json()
    except:
        raise CustomValidationError(
            ErrorCode.INVALID_REQUEST_FORMAT,
            "Invalid JSON in request body"
        )
    
    # Validate against schema
    try:
        validated = validate_request(ChallengeRequest, body)
    except ValidationError as e:
        raise CustomValidationError(
            ErrorCode.VALIDATION_ERROR,
            str(e),
            details=e.errors()
        )
    
    # Forward to challenge service
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{CHALLENGE_SERVICE_URL}/generate",
            json=validated.dict(),
            headers={
                "X-Internal-Token": INTERNAL_AUTH_TOKEN,
                "X-Forwarded-For": request.client.host,
                "User-Agent": request.headers.get("User-Agent", "")
            }
        )
        
        return JSONResponse(
            status_code=response.status_code,
            content=response.json()
        )

# ============================================================================
# VERIFY ENDPOINT (WITH FILE VALIDATION)
# ============================================================================

@app.post("/v1/verify")
async def verify_challenge(
    request: Request,
    video: UploadFile = File(...),
    device_id: str = Form(...),
    challenge_id: str = Form(...),
    token_id: str = Form(...),
    audio_challenge: str = Form(None),
    camera_attestation: str = Form(None)
):
    """
    Verify challenge with comprehensive file validation
    
    Validation:
    - Request parameters (device_id, challenge_id, token)
    - File size limits
    - MIME type verification
    - Content sniffing (magic bytes)
    - Polyglot file detection
    - Malformed file detection
    """
    
    # Validate request parameters
    try:
        verify_req = VerifyRequest(
            device_id=device_id,
            challenge_id=challenge_id,
            token_id=token_id,
            audio_challenge=audio_challenge,
            camera_attestation=camera_attestation
        )
    except ValidationError as e:
        raise CustomValidationError(
            ErrorCode.VALIDATION_ERROR,
            "Request validation failed",
            details=e.errors()
        )
    
    # Validate video file
    try:
        file_validation = await file_validator.validate_video_upload(
            file=video,
            expected_duration_range=(1.0, 10.0)  # 1-10 seconds
        )
        
        if not file_validation["valid"]:
            raise CustomValidationError(
                ErrorCode.INVALID_VIDEO_FORMAT,
                "Video validation failed"
            )
        
    except ValueError as e:
        raise CustomValidationError(
            ErrorCode.INVALID_VIDEO_FORMAT,
            str(e)
        )
    
    # Reset file pointer
    await video.seek(0)
    
    # Forward to verification service
    async with httpx.AsyncClient(timeout=30.0) as client:
        # Prepare multipart form data
        files = {"video": (video.filename, video.file, video.content_type)}
        data = {
            "device_id": verify_req.device_id,
            "challenge_id": verify_req.challenge_id,
            "token_id": verify_req.token_id
        }
        
        if verify_req.audio_challenge:
            data["audio_challenge"] = verify_req.audio_challenge
        
        if verify_req.camera_attestation:
            data["camera_attestation"] = verify_req.camera_attestation
        
        response = await client.post(
            f"{VERIFICATION_SERVICE_URL}/verify",
            files=files,
            data=data,
            headers={"X-Internal-Token": INTERNAL_AUTH_TOKEN}
        )
        
        return JSONResponse(
            status_code=response.status_code,
            content=response.json()
        )

# ============================================================================
# FINALIZE ENDPOINT (WITH VALIDATION)
# ============================================================================

@app.post("/v1/finalize")
async def finalize_session(request: Request):
    """Finalize verification session with validation"""
    
    try:
        body = await request.json()
    except:
        raise CustomValidationError(
            ErrorCode.INVALID_REQUEST_FORMAT,
            "Invalid JSON"
        )
    
    try:
        validated = validate_request(FinalizeRequest, body)
    except ValidationError as e:
        raise CustomValidationError(
            ErrorCode.VALIDATION_ERROR,
            str(e),
            details=e.errors()
        )
    
    # Forward to verification service
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{VERIFICATION_SERVICE_URL}/finalize",
            json=validated.dict(),
            headers={"X-Internal-Token": INTERNAL_AUTH_TOKEN}
        )
        
        return JSONResponse(
            status_code=response.status_code,
            content=response.json()
        )

# ============================================================================
# ADMIN ENDPOINTS (WITH VALIDATION)
# ============================================================================

@app.post("/admin/device/revoke")
async def revoke_device(request: Request):
    """Revoke device trust with strict validation"""
    
    # Check admin auth
    admin_token = request.headers.get("X-Admin-Token")
    if admin_token != os.getenv("ADMIN_TOKEN", "admin_secret"):
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    try:
        body = await request.json()
    except:
        raise CustomValidationError(
            ErrorCode.INVALID_REQUEST_FORMAT,
            "Invalid JSON"
        )
    
    try:
        validated = validate_request(AdminRevokeRequest, body)
    except ValidationError as e:
        raise CustomValidationError(
            ErrorCode.VALIDATION_ERROR,
            str(e),
            details=e.errors()
        )
    
    # Forward to admin service
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{VERIFICATION_SERVICE_URL}/admin/revoke",
            json=validated.dict(),
            headers={"X-Internal-Token": INTERNAL_AUTH_TOKEN}
        )
        
        return JSONResponse(
            status_code=response.status_code,
            content=response.json()
        )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)