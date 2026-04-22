"""
Challenge Service with High-Entropy Generation
- Cryptographically secure randomness (CSPRNG)
- Multi-step combinatorial challenges
- Template rotation and A/B testing
- >= 20 bits entropy per session
"""

from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel
import redis.asyncio as redis
import os
import time
import sys
from typing import List, Dict, Any, Optional
from datetime import datetime

# Add shared modules to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'shared'))

from error_codes import ErrorCode, ValidationError, InternalError
from token_signing import TokenSigner
from challenge_entropy import ChallengeGenerator, CHALLENGE_TEMPLATES
from template_rotation import TemplateRotationManager

# ============================================================================
# CONFIGURATION
# ============================================================================

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")
CHALLENGE_TTL = int(os.getenv("CHALLENGE_TTL", "300"))
INTERNAL_AUTH_TOKEN = os.getenv("INTERNAL_AUTH_TOKEN", "secret")
TARGET_SESSION_ENTROPY = float(os.getenv("TARGET_SESSION_ENTROPY", "20.0"))
ENABLE_AB_TESTING = os.getenv("ENABLE_AB_TESTING", "true").lower() == "true"

# ============================================================================
# MODELS
# ============================================================================

class ChallengeRequest(BaseModel):
    device_id: str
    trust_level: Optional[str] = "unknown"

class ChallengeResponse(BaseModel):
    challenges: List[Dict[str, Any]]
    session_entropy_bits: float
    fast_track_enabled: bool = False

# ============================================================================
# FASTAPI APP
# ============================================================================

app = FastAPI(
    title="Certivo Challenge Service",
    description="High-entropy cryptographic challenge generation",
    version="2.0.0"
)

redis_client = None
token_signer = None
challenge_generator = None
rotation_manager = None

# ============================================================================
# STARTUP/SHUTDOWN
# ============================================================================

@app.on_event("startup")
async def startup():
    global redis_client, token_signer, challenge_generator, rotation_manager
    
    redis_client = await redis.from_url(REDIS_URL, decode_responses=True)
    token_signer = TokenSigner()
    challenge_generator = ChallengeGenerator()
    rotation_manager = TemplateRotationManager(redis_client)
    
    print("✅ Challenge Service started with high-entropy generation")
    print(f"   Target session entropy: {TARGET_SESSION_ENTROPY} bits")
    print(f"   A/B testing: {'enabled' if ENABLE_AB_TESTING else 'disabled'}")

@app.on_event("shutdown")
async def shutdown():
    if redis_client:
        await redis_client.close()
    print("🛑 Challenge Service shutdown")

# ============================================================================
# HEALTH CHECK
# ============================================================================

@app.get("/health")
async def health_check():
    try:
        await redis_client.ping()
        redis_status = "healthy"
    except Exception as e:
        redis_status = f"unhealthy: {str(e)}"
    
    return {
        "status": "healthy",
        "service": "challenge-service",
        "redis": redis_status,
        "timestamp": time.time(),
        "entropy_target": TARGET_SESSION_ENTROPY
    }

# ============================================================================
# CHALLENGE GENERATION
# ============================================================================

@app.post("/generate")
async def generate_challenge(
    request: ChallengeRequest,
    x_internal_token: str = Header(None)
):
    """
    Generate high-entropy multi-step challenges
    
    Returns:
        - List of challenges with >= 20 bits total entropy
        - Each challenge includes entropy calculation
        - Signed tokens for integrity
    """
    
    # Auth check
    if x_internal_token != INTERNAL_AUTH_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    # Validate device_id
    if not request.device_id:
        raise ValidationError(
            ErrorCode.MISSING_REQUIRED_FIELD,
            "device_id is required",
            field="device_id"
        )
    
    # Determine trust level
    trust_level = request.trust_level or "unknown"
    
    # A/B test for template selection (if enabled)
    if ENABLE_AB_TESTING and trust_level == "unknown":
        # Test two high-entropy templates
        selected_template = await rotation_manager.select_template_for_ab_test(
            device_id=request.device_id,
            variant_a="combinatorial_challenge",
            variant_b="mega_combinatorial"
        )
        print(f"A/B Test: Device {request.device_id[:8]} → {selected_template}")
    
    # Generate session challenges with entropy target
    session_challenges = challenge_generator.generate_session_challenges(
        device_id=request.device_id,
        trust_level=trust_level,
        target_entropy_bits=TARGET_SESSION_ENTROPY
    )
    
    # Calculate total session entropy
    session_entropy = challenge_generator.calculate_session_entropy(session_challenges)
    
    # Verify entropy target met
    if session_entropy < TARGET_SESSION_ENTROPY:
        raise InternalError(
            f"Generated entropy {session_entropy:.2f} bits below target {TARGET_SESSION_ENTROPY} bits"
        )
    
    # Convert to API response format with signed tokens
    api_challenges = []
    
    for challenge_data in session_challenges:
        challenge_id = challenge_data["challenge_id"]
        
        # Store challenge metadata in Redis
        challenge_key = f"challenge:{challenge_id}"
        
        # Create metadata
        metadata = {
            "challenge_id": challenge_id,
            "device_id": request.device_id,
            "template_id": challenge_data["template_id"],
            "entropy_bits": challenge_data["entropy_bits"],
            "steps": str(challenge_data["steps"]),  # JSON string
            "consumed": "false",
            "created_at": datetime.utcnow().isoformat(),
            "session_salt": challenge_data["session_salt"]
        }
        
        # Store in Redis
        await redis_client.hset(challenge_key, mapping=metadata)
        await redis_client.expire(challenge_key, CHALLENGE_TTL)
        
        # Generate nonce for replay protection
        import secrets
        nonce = secrets.token_urlsafe(32)
        
        # Update nonce in Redis
        await redis_client.hset(challenge_key, "nonce", nonce)
        
        # Create signed token
        from datetime import timedelta
        expires_at = datetime.utcnow() + timedelta(seconds=CHALLENGE_TTL)
        
        token_id = token_signer.create_challenge_token(
            challenge_id=challenge_id,
            device_id=request.device_id,
            nonce=nonce,
            allowed_actions=[step["action"] for step in challenge_data["steps"]],
            expires_at=expires_at
        )
        
        # Create API response
        api_challenges.append({
            "challenge_id": challenge_id,
            "token_id": token_id,
            "instruction": challenge_data["instruction"],
            "steps": challenge_data["steps"],
            "difficulty": "high" if challenge_data["entropy_bits"] > 15 else "medium",
            "expires_at": expires_at.isoformat() + "Z",
            "entropy_bits": round(challenge_data["entropy_bits"], 2),
            "template_id": challenge_data["template_id"]
        })
    
    # Track template usage for rotation
    for challenge in session_challenges:
        template_id = challenge["template_id"]
        await redis_client.hincrby(f"template_usage:{template_id}", "count", 1)
    
    return {
        "challenges": api_challenges,
        "session_entropy_bits": round(session_entropy, 2),
        "entropy_target_met": session_entropy >= TARGET_SESSION_ENTROPY,
        "fast_track_enabled": trust_level == "high"
    }

# ============================================================================
# ENTROPY STATISTICS
# ============================================================================

@app.get("/entropy/stats")
async def get_entropy_stats(
    x_internal_token: str = Header(None)
):
    """Get entropy generation statistics"""
    
    if x_internal_token != INTERNAL_AUTH_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    stats = challenge_generator.get_entropy_statistics()
    
    return {
        "statistics": stats,
        "target_entropy": TARGET_SESSION_ENTROPY,
        "timestamp": datetime.utcnow().isoformat()
    }

# ============================================================================
# TEMPLATE MANAGEMENT
# ============================================================================

@app.get("/templates")
async def list_templates(
    x_internal_token: str = Header(None)
):
    """List available challenge templates"""
    
    if x_internal_token != INTERNAL_AUTH_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    templates_info = []
    
    for template_id, template in CHALLENGE_TEMPLATES.items():
        templates_info.append({
            "template_id": template_id,
            "description": template.description,
            "steps": len(template.steps),
            "min_entropy_bits": round(template.min_entropy_bits, 2),
            "theoretical_entropy": round(template.calculate_entropy(), 2)
        })
    
    return {
        "templates": templates_info,
        "total_templates": len(templates_info)
    }

@app.post("/templates/rotate")
async def rotate_templates(
    x_internal_token: str = Header(None)
):
    """Manually trigger template rotation"""
    
    if x_internal_token != INTERNAL_AUTH_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    active_templates = await rotation_manager.rotate_templates()
    
    return {
        "rotated": True,
        "active_templates": active_templates,
        "timestamp": datetime.utcnow().isoformat()
    }

@app.get("/templates/active")
async def get_active_templates(
    x_internal_token: str = Header(None)
):
    """Get currently active templates"""
    
    if x_internal_token != INTERNAL_AUTH_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    active = await rotation_manager.get_active_templates()
    
    return {
        "active_templates": active,
        "count": len(active)
    }

# ============================================================================
# A/B TESTING
# ============================================================================

@app.get("/ab-test/results")
async def get_ab_test_results(
    variant_a: str,
    variant_b: str,
    x_internal_token: str = Header(None)
):
    """Get A/B test results for two template variants"""
    
    if x_internal_token != INTERNAL_AUTH_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    results = await rotation_manager.get_ab_test_results(variant_a, variant_b)
    
    total = sum(results.values())
    
    return {
        "variant_a": variant_a,
        "variant_b": variant_b,
        "results": results,
        "total_tests": total,
        "variant_a_percentage": (results.get(variant_a, 0) / total * 100) if total > 0 else 0,
        "variant_b_percentage": (results.get(variant_b, 0) / total * 100) if total > 0 else 0
    }

@app.get("/templates/{template_id}/effectiveness")
async def get_template_effectiveness(
    template_id: str,
    x_internal_token: str = Header(None)
):
    """Get effectiveness metrics for a template"""
    
    if x_internal_token != INTERNAL_AUTH_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    effectiveness = await rotation_manager.get_template_effectiveness(template_id)
    
    return effectiveness

# ============================================================================
# TOKEN VALIDATION (FROM PART 3.2)
# ============================================================================

@app.post("/validate-token")
async def validate_token(
    token_id: str,
    challenge_id: str,
    device_id: str,
    x_internal_token: str = Header(None)
):
    """Validate challenge token (from Part 3.2)"""
    
    if x_internal_token != INTERNAL_AUTH_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    # Verify token signature
    payload = token_signer.verify_challenge_token(token_id)
    
    if not payload:
        raise HTTPException(status_code=403, detail="Invalid token")
    
    # Verify challenge exists
    challenge_key = f"challenge:{challenge_id}"
    challenge_data = await redis_client.hgetall(challenge_key)
    
    if not challenge_data:
        raise HTTPException(status_code=404, detail="Challenge not found")
    
    # Verify not consumed
    if challenge_data.get('consumed') == 'true':
        raise HTTPException(status_code=403, detail="Challenge already used")
    
    return {
        "valid": True,
        "nonce": challenge_data.get('nonce'),
        "allowed_actions": payload.get('allowed_actions'),
        "entropy_bits": float(challenge_data.get('entropy_bits', 0))
    }

@app.post("/consume-token")
async def consume_token(
    challenge_id: str,
    nonce: str,
    x_internal_token: str = Header(None)
):
    """Mark challenge as consumed (from Part 3.2)"""
    
    if x_internal_token != INTERNAL_AUTH_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    challenge_key = f"challenge:{challenge_id}"
    challenge_data = await redis_client.hgetall(challenge_key)
    
    if not challenge_data:
        raise HTTPException(status_code=404, detail="Challenge not found")
    
    if challenge_data.get('nonce') != nonce:
        raise HTTPException(status_code=403, detail="Nonce mismatch")
    
    if challenge_data.get('consumed') == 'true':
        raise HTTPException(status_code=403, detail="Already consumed")
    
    # Mark as consumed
    await redis_client.hset(challenge_key, 'consumed', 'true')
    
    return {
        "consumed": True,
        "challenge_id": challenge_id
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)