from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Boolean, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import QueuePool
from datetime import datetime, timedelta
import json

# ============================================================================
# DATABASE OPTIMIZATION - Connection pooling
# ============================================================================

DATABASE_URL = "sqlite:///certivo_v2.db"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=QueuePool,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
    pool_recycle=3600,
    echo=False
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# ============================================================================
# DATABASE MODELS
# ============================================================================

class SessionRecord(Base):
    """Stores final verification session results"""
    __tablename__ = "sessions"
    
    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String, unique=True, index=True, nullable=False)
    device_id = Column(String, index=True, nullable=False)
    trust_score = Column(Float, nullable=False)
    trust_level = Column(String, nullable=False)
    failed_challenges = Column(Integer, default=0)
    total_challenges = Column(Integer, nullable=False)
    fast_track = Column(Boolean, default=False)
    timestamp_utc = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)


class ChallengeResult(Base):
    """Stores individual challenge verification results"""
    __tablename__ = "challenge_results"
    
    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String, index=True, nullable=False)
    device_id = Column(String, index=True, nullable=False)
    challenge_id = Column(String, unique=True, index=True, nullable=False)
    
    instruction = Column(String, nullable=False)
    expected_direction = Column(String, nullable=True)
    difficulty = Column(String, default="medium")
    
    challenge_passed = Column(Boolean, nullable=False, index=True)
    liveness_score = Column(Float, nullable=False)
    direction_detected = Column(String, nullable=True)
    direction_matched = Column(Boolean, default=False)
    
    fast_track = Column(Boolean, default=False)
    video_size_bytes = Column(Integer, nullable=True)
    frames_analyzed = Column(Integer, nullable=True)
    face_detected_frames = Column(Integer, nullable=True)
    
    timestamp_utc = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)


class TrustedDevice(Base):
    """Tracks trusted devices for fast-track verification"""
    __tablename__ = "trusted_devices"
    
    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(String, unique=True, index=True, nullable=False)
    
    trust_level = Column(String, nullable=False, index=True)
    total_verifications = Column(Integer, default=1)
    successful_verifications = Column(Integer, default=0)
    
    # SECURITY FEATURE 4: Trust revocation tracking
    trust_revoked = Column(Boolean, default=False, index=True)
    revoked_at = Column(DateTime, nullable=True)
    revocation_reason = Column(String, nullable=True)
    
    first_seen_utc = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_verified_utc = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    trusted_since_utc = Column(DateTime, nullable=True)


class ActiveChallenge(Base):
    """Stores active challenges for validation"""
    __tablename__ = "active_challenges"
    
    id = Column(Integer, primary_key=True, index=True)
    challenge_id = Column(String, unique=True, index=True, nullable=False)
    device_id = Column(String, index=True, nullable=False)
    
    instruction = Column(String, nullable=False)
    expected_direction = Column(String, nullable=True)
    expected_movement = Column(String, nullable=True)
    difficulty = Column(String, default="medium")
    
    token_id = Column(String, nullable=True, index=True)
    expires_at = Column(DateTime, nullable=False, index=True)
    used = Column(Boolean, default=False, index=True)
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)


class BotReport(Base):
    """Stores bot detection reports for analysis"""
    __tablename__ = "bot_reports"
    
    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(String, index=True, nullable=False)
    
    bot_detected = Column(Boolean, nullable=False, index=True)
    suspicion_score = Column(Integer, nullable=False, index=True)
    
    frontend_checks = Column(Text, nullable=True)
    fingerprint = Column(Text, nullable=True)
    backend_signals = Column(Text, nullable=True)
    
    ip_address = Column(String, nullable=True, index=True)
    user_agent = Column(String, nullable=True)
    
    timestamp_utc = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)


class SuspiciousDevice(Base):
    """
    SECURITY FEATURE: Track devices flagged for suspicious activity.
    
    Devices are flagged when:
    - Video integrity checks fail
    - Bot-like patterns detected in verification metrics
    - Repeated failures
    - Unusual usage patterns
    """
    __tablename__ = "suspicious_devices"
    
    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(String, index=True, nullable=False)
    
    reason = Column(String, nullable=False)
    suspicion_score = Column(Integer, nullable=False, index=True)
    
    # Evidence
    evidence = Column(Text, nullable=True)  # JSON data
    
    # Status
    is_blocked = Column(Boolean, default=False, index=True)
    
    flagged_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)


# ============================================================================
# DATABASE INIT
# ============================================================================

def init_db():
    """Initialize database tables"""
    Base.metadata.create_all(bind=engine)
    print("✅ Database initialized with connection pooling + security features")
    print(f"   Pool size: 10 connections")
    print(f"   Max overflow: 20 connections")
    print(f"   Security: Suspicious device tracking enabled")


def get_db():
    """Get database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ============================================================================
# BOT REPORT OPERATIONS
# ============================================================================

def store_bot_report(db, device_id: str, bot_detected: bool, suspicion_score: int,
                    frontend_checks: dict = None, fingerprint: dict = None,
                    backend_signals: dict = None, ip_address: str = None,
                    user_agent: str = None):
    """Store bot detection report"""
    report = BotReport(
        device_id=device_id,
        bot_detected=bot_detected,
        suspicion_score=suspicion_score,
        frontend_checks=json.dumps(frontend_checks) if frontend_checks else None,
        fingerprint=json.dumps(fingerprint) if fingerprint else None,
        backend_signals=json.dumps(backend_signals) if backend_signals else None,
        ip_address=ip_address,
        user_agent=user_agent
    )
    db.add(report)
    db.commit()
    return report


def get_bot_reports(db, device_id: str = None, limit: int = 50):
    """Get bot detection reports"""
    query = db.query(BotReport)
    
    if device_id:
        query = query.filter(BotReport.device_id == device_id)
    
    return query.order_by(BotReport.timestamp_utc.desc()).limit(limit).all()


def get_bot_statistics(db):
    """Get overall bot detection statistics"""
    total_reports = db.query(BotReport).count()
    bots_detected = db.query(BotReport).filter(BotReport.bot_detected == True).count()
    
    # Also count suspicious devices
    suspicious_count = db.query(SuspiciousDevice).filter(
        SuspiciousDevice.is_blocked == True
    ).count()
    
    if total_reports == 0:
        return {
            "total_reports": 0,
            "bots_detected": 0,
            "bot_rate": 0.0,
            "suspicious_devices": suspicious_count
        }
    
    return {
        "total_reports": total_reports,
        "bots_detected": bots_detected,
        "bot_rate": round((bots_detected / total_reports) * 100, 2),
        "suspicious_devices": suspicious_count
    }


# ============================================================================
# SECURITY FEATURE: SUSPICIOUS DEVICE OPERATIONS
# ============================================================================

def flag_suspicious_device(
    db,
    device_id: str,
    reason: str,
    suspicion_score: int,
    evidence: dict = None,
    auto_block: bool = True
):
    """
    Flag a device as suspicious.
    
    Args:
        db: Database session
        device_id: Device to flag
        reason: Why it's suspicious
        suspicion_score: 1-10 severity score
        evidence: Optional dict of evidence
        auto_block: If True and score >= 7, automatically block
    """
    
    # Check if already flagged
    existing = db.query(SuspiciousDevice).filter(
        SuspiciousDevice.device_id == device_id
    ).first()
    
    if existing:
        # Update existing record
        existing.reason = f"{existing.reason}; {reason}"
        existing.suspicion_score = max(existing.suspicion_score, suspicion_score)
        existing.flagged_at = datetime.utcnow()
        
        if auto_block and suspicion_score >= 7:
            existing.is_blocked = True
        
        if evidence:
            existing.evidence = json.dumps(evidence)
    else:
        # Create new record
        suspicious = SuspiciousDevice(
            device_id=device_id,
            reason=reason,
            suspicion_score=suspicion_score,
            evidence=json.dumps(evidence) if evidence else None,
            is_blocked=(auto_block and suspicion_score >= 7)
        )
        db.add(suspicious)
    
    db.commit()
    
    print(f"🚨 Device {device_id} flagged: {reason} (score: {suspicion_score})")
    
    return True


def get_suspicious_devices(db, device_id: str = None, limit: int = 50):
    """Get list of suspicious devices"""
    query = db.query(SuspiciousDevice)
    
    if device_id:
        query = query.filter(SuspiciousDevice.device_id == device_id)
    
    return query.order_by(SuspiciousDevice.flagged_at.desc()).limit(limit).all()


def unblock_suspicious_device(db, device_id: str):
    """Unblock a suspicious device (admin action)"""
    device = db.query(SuspiciousDevice).filter(
        SuspiciousDevice.device_id == device_id
    ).first()
    
    if device:
        device.is_blocked = False
        db.commit()
        print(f"✅ Device {device_id} unblocked")
        return True
    
    return False


# ============================================================================
# CHALLENGE OPERATIONS
# ============================================================================

def store_challenge(db, challenge_id: str, device_id: str, instruction: str, 
                   expected_direction: str, token_id: str, expires_at, 
                   difficulty: str = "medium", expected_movement: str = None):
    """Store a challenge in the database"""
    challenge = ActiveChallenge(
        challenge_id=challenge_id,
        device_id=device_id,
        instruction=instruction,
        expected_direction=expected_direction,
        expected_movement=expected_movement,
        difficulty=difficulty,
        token_id=token_id,
        expires_at=expires_at,
        used=False
    )
    db.add(challenge)
    db.commit()
    return challenge


def get_challenge(db, challenge_id: str):
    """Retrieve a challenge by ID"""
    return db.query(ActiveChallenge).filter(
        ActiveChallenge.challenge_id == challenge_id
    ).first()


def mark_challenge_used(db, challenge_id: str):
    """Mark a challenge as used"""
    challenge = get_challenge(db, challenge_id)
    if challenge:
        challenge.used = True
        db.commit()
        return True
    return False


def delete_challenge(db, challenge_id: str):
    """Delete a challenge after use"""
    challenge = get_challenge(db, challenge_id)
    if challenge:
        db.delete(challenge)
        db.commit()
        return True
    return False


def cleanup_expired_challenges(db):
    """Remove expired challenges from database"""
    now = datetime.utcnow()
    expired = db.query(ActiveChallenge).filter(
        ActiveChallenge.expires_at < now
    ).delete()
    db.commit()
    
    if expired > 0:
        print(f"🧹 Cleaned up {expired} expired challenge(s)")
    
    return expired


# ============================================================================
# CHALLENGE RESULT OPERATIONS
# ============================================================================

def store_challenge_result(db, session_id: str, device_id: str, challenge_id: str,
                          instruction: str, expected_direction: str,
                          challenge_passed: bool, liveness_score: float,
                          direction_detected: str, direction_matched: bool,
                          fast_track: bool = False, video_size_bytes: int = None,
                          frames_analyzed: int = None, face_detected_frames: int = None,
                          difficulty: str = "medium"):
    """Store individual challenge result"""
    result = ChallengeResult(
        session_id=session_id,
        device_id=device_id,
        challenge_id=challenge_id,
        instruction=instruction,
        expected_direction=expected_direction,
        difficulty=difficulty,
        challenge_passed=challenge_passed,
        liveness_score=liveness_score,
        direction_detected=direction_detected,
        direction_matched=direction_matched,
        fast_track=fast_track,
        video_size_bytes=video_size_bytes,
        frames_analyzed=frames_analyzed,
        face_detected_frames=face_detected_frames
    )
    db.add(result)
    db.commit()
    return result


def get_session_results(db, device_id: str):
    """Get all challenge results for a device's current session"""
    cutoff = datetime.utcnow() - timedelta(minutes=10)
    
    return db.query(ChallengeResult).filter(
        ChallengeResult.device_id == device_id,
        ChallengeResult.timestamp_utc >= cutoff
    ).order_by(ChallengeResult.timestamp_utc.asc()).all()


def get_device_verification_history(db, device_id: str, limit: int = 20):
    """Get full verification history for a device"""
    return db.query(ChallengeResult).filter(
        ChallengeResult.device_id == device_id
    ).order_by(ChallengeResult.timestamp_utc.desc()).limit(limit).all()


# ============================================================================
# SESSION OPERATIONS
# ============================================================================

def store_session(db, session_id: str, device_id: str, trust_score: float,
                 trust_level: str, failed_challenges: int, total_challenges: int,
                 fast_track: bool = False):
    """Store final session result"""
    session = SessionRecord(
        session_id=session_id,
        device_id=device_id,
        trust_score=trust_score,
        trust_level=trust_level,
        failed_challenges=failed_challenges,
        total_challenges=total_challenges,
        fast_track=fast_track
    )
    db.add(session)
    db.commit()
    return session


def get_session(db, session_id: str):
    """Retrieve a session by ID"""
    return db.query(SessionRecord).filter(
        SessionRecord.session_id == session_id
    ).first()


# ============================================================================
# TRUSTED DEVICE OPERATIONS
# ============================================================================

def get_trusted_device(db, device_id: str):
    """Get trusted device record"""
    return db.query(TrustedDevice).filter(
        TrustedDevice.device_id == device_id
    ).first()


def is_device_trusted(db, device_id: str) -> bool:
    """
    Check if a device is trusted.
    
    SECURITY FEATURE 4: Also checks if trust was revoked.
    """
    device = get_trusted_device(db, device_id)
    if device:
        # Not trusted if revoked
        if device.trust_revoked:
            return False
        
        return device.trust_level == "high"
    return False


def update_device_trust(db, device_id: str, trust_level: str, 
                       verification_passed: bool = True):
    """Update or create trusted device record"""
    device = get_trusted_device(db, device_id)
    
    if device:
        device.total_verifications += 1
        if verification_passed:
            device.successful_verifications += 1
        device.trust_level = trust_level
        device.last_verified_utc = datetime.utcnow()
        
        # Grant trust if high level and not revoked
        if trust_level == "high" and not device.trust_revoked:
            if not device.trusted_since_utc:
                device.trusted_since_utc = datetime.utcnow()
    else:
        device = TrustedDevice(
            device_id=device_id,
            trust_level=trust_level,
            total_verifications=1,
            successful_verifications=1 if verification_passed else 0,
            trusted_since_utc=datetime.utcnow() if trust_level == "high" else None,
            trust_revoked=False
        )
        db.add(device)
    
    db.commit()
    return device


def revoke_device_trust(db, device_id: str, reason: str):
    """
    SECURITY FEATURE 4: Revoke trust from a device.
    
    Used when:
    - Repeated verification failures
    - Suspicious activity detected
    - Manual admin action
    """
    device = get_trusted_device(db, device_id)
    
    if device:
        device.trust_revoked = True
        device.revoked_at = datetime.utcnow()
        device.revocation_reason = reason
        device.trust_level = "low"
        db.commit()
        
        print(f"⚠️  Trust revoked for device {device_id}: {reason}")
        return True
    
    return False


def restore_device_trust(db, device_id: str):
    """Restore trust to a device (admin action)"""
    device = get_trusted_device(db, device_id)
    
    if device:
        device.trust_revoked = False
        device.revoked_at = None
        device.revocation_reason = None
        db.commit()
        
        print(f"✅ Trust restored for device {device_id}")
        return True
    
    return False


def get_device_stats(db, device_id: str):
    """Get statistics for a device"""
    device = get_trusted_device(db, device_id)
    if not device:
        return None
    
    success_rate = 0
    if device.total_verifications > 0:
        success_rate = (device.successful_verifications / device.total_verifications) * 100
    
    # Check if flagged as suspicious
    suspicious = db.query(SuspiciousDevice).filter(
        SuspiciousDevice.device_id == device_id
    ).first()
    
    return {
        "device_id": device_id,
        "trust_level": device.trust_level,
        "total_verifications": device.total_verifications,
        "successful_verifications": device.successful_verifications,
        "success_rate": round(success_rate, 2),
        "first_seen": device.first_seen_utc.isoformat(),
        "last_verified": device.last_verified_utc.isoformat(),
        "trusted_since": device.trusted_since_utc.isoformat() if device.trusted_since_utc else None,
        "trust_revoked": device.trust_revoked,
        "revoked_at": device.revoked_at.isoformat() if device.revoked_at else None,
        "revocation_reason": device.revocation_reason,
        "is_suspicious": suspicious is not None,
        "is_blocked": suspicious.is_blocked if suspicious else False
    }


# ============================================================================
# ANALYTICS QUERIES
# ============================================================================

def get_recent_sessions(db, limit: int = 10):
    """Get most recent verification sessions"""
    return db.query(SessionRecord).order_by(
        SessionRecord.timestamp_utc.desc()
    ).limit(limit).all()


def get_failed_challenges(db, limit: int = 20):
    """Get recent failed challenges for analysis"""
    return db.query(ChallengeResult).filter(
        ChallengeResult.challenge_passed == False
    ).order_by(ChallengeResult.timestamp_utc.desc()).limit(limit).all()


def get_success_rate_by_direction(db):
    """Analyze success rates by direction"""
    results = db.query(ChallengeResult).filter(
        ChallengeResult.expected_direction.isnot(None)
    ).all()
    
    stats = {"left": {"total": 0, "passed": 0}, "right": {"total": 0, "passed": 0}}
    
    for result in results:
        direction = result.expected_direction
        if direction in stats:
            stats[direction]["total"] += 1
            if result.challenge_passed:
                stats[direction]["passed"] += 1
    
    for direction in stats:
        if stats[direction]["total"] > 0:
            stats[direction]["success_rate"] = round(
                (stats[direction]["passed"] / stats[direction]["total"]) * 100, 2
            )
        else:
            stats[direction]["success_rate"] = 0
    
    return stats


# Initialize database on module load
init_db()