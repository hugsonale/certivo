from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Boolean, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime
import json

DATABASE_URL = "sqlite:///certivo_v2.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
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
    trust_level = Column(String, nullable=False)  # "high", "medium", "low"
    failed_challenges = Column(Integer, default=0)
    total_challenges = Column(Integer, nullable=False)
    fast_track = Column(Boolean, default=False)
    timestamp_utc = Column(DateTime, default=datetime.utcnow, nullable=False)


class ChallengeResult(Base):
    """Stores individual challenge verification results"""
    __tablename__ = "challenge_results"
    
    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String, index=True, nullable=False)
    device_id = Column(String, index=True, nullable=False)
    challenge_id = Column(String, unique=True, index=True, nullable=False)
    
    # Challenge details
    instruction = Column(String, nullable=False)
    expected_direction = Column(String, nullable=True)  # "left", "right", or None
    difficulty = Column(String, default="medium")
    
    # Verification results
    challenge_passed = Column(Boolean, nullable=False)
    liveness_score = Column(Float, nullable=False)
    direction_detected = Column(String, nullable=True)  # "left", "right", "none", "ambiguous"
    direction_matched = Column(Boolean, default=False)
    
    # Metadata
    fast_track = Column(Boolean, default=False)
    video_size_bytes = Column(Integer, nullable=True)
    frames_analyzed = Column(Integer, nullable=True)
    face_detected_frames = Column(Integer, nullable=True)
    
    timestamp_utc = Column(DateTime, default=datetime.utcnow, nullable=False)


class TrustedDevice(Base):
    """Tracks trusted devices for fast-track verification"""
    __tablename__ = "trusted_devices"
    
    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(String, unique=True, index=True, nullable=False)
    
    # Trust metrics
    trust_level = Column(String, nullable=False)  # "high", "medium", "low"
    total_verifications = Column(Integer, default=1)
    successful_verifications = Column(Integer, default=0)
    
    # Timestamps
    first_seen_utc = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_verified_utc = Column(DateTime, default=datetime.utcnow, nullable=False)
    trusted_since_utc = Column(DateTime, nullable=True)  # When it became trusted


class ActiveChallenge(Base):
    """Stores active challenges for validation (replaces in-memory store)"""
    __tablename__ = "active_challenges"
    
    id = Column(Integer, primary_key=True, index=True)
    challenge_id = Column(String, unique=True, index=True, nullable=False)
    device_id = Column(String, index=True, nullable=False)
    
    # Challenge details
    instruction = Column(String, nullable=False)
    expected_direction = Column(String, nullable=True)
    expected_movement = Column(String, nullable=True)
    difficulty = Column(String, default="medium")
    
    # Token and expiration
    token_id = Column(String, nullable=True)
    expires_at = Column(DateTime, nullable=False)
    used = Column(Boolean, default=False)
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class BotReport(Base):
    """Stores bot detection reports for analysis"""
    __tablename__ = "bot_reports"
    
    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(String, index=True, nullable=False)
    
    # Detection results
    bot_detected = Column(Boolean, nullable=False)
    suspicion_score = Column(Integer, nullable=False)
    
    # Frontend checks (JSON)
    frontend_checks = Column(Text, nullable=True)  # JSON string
    
    # Browser fingerprint (JSON)
    fingerprint = Column(Text, nullable=True)  # JSON string
    
    # Backend signals (JSON)
    backend_signals = Column(Text, nullable=True)  # JSON string
    
    # Network info
    ip_address = Column(String, nullable=True)
    user_agent = Column(String, nullable=True)
    
    timestamp_utc = Column(DateTime, default=datetime.utcnow, nullable=False)

# ============================================================================
# DATABASE HELPER FUNCTIONS
# ============================================================================

def init_db():
    """Initialize database tables"""
    Base.metadata.create_all(bind=engine)
    print("✅ Database initialized successfully")


def get_db():
    """Get database session (use with context manager)"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


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
    """Get bot detection reports, optionally filtered by device"""
    query = db.query(BotReport)
    
    if device_id:
        query = query.filter(BotReport.device_id == device_id)
    
    return query.order_by(BotReport.timestamp_utc.desc()).limit(limit).all()


def get_bot_statistics(db):
    """Get overall bot detection statistics"""
    total_reports = db.query(BotReport).count()
    bots_detected = db.query(BotReport).filter(BotReport.bot_detected == True).count()
    
    if total_reports == 0:
        return {"total_reports": 0, "bots_detected": 0, "bot_rate": 0.0}
    
    return {
        "total_reports": total_reports,
        "bots_detected": bots_detected,
        "bot_rate": round((bots_detected / total_reports) * 100, 2)
    }


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
    """Mark a challenge as used (prevents replay attacks)"""
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
    # Get results from the last 10 minutes (active session)
    from datetime import timedelta
    cutoff = datetime.utcnow() - timedelta(minutes=10)
    
    return db.query(ChallengeResult).filter(
        ChallengeResult.device_id == device_id,
        ChallengeResult.timestamp_utc >= cutoff
    ).order_by(ChallengeResult.timestamp_utc.asc()).all()


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
    """Check if a device is trusted"""
    device = get_trusted_device(db, device_id)
    if device:
        return device.trust_level == "high"
    return False


def update_device_trust(db, device_id: str, trust_level: str, 
                       verification_passed: bool = True):
    """Update or create trusted device record"""
    device = get_trusted_device(db, device_id)
    
    if device:
        # Update existing device
        device.total_verifications += 1
        if verification_passed:
            device.successful_verifications += 1
        device.trust_level = trust_level
        device.last_verified_utc = datetime.utcnow()
        
        # Mark as trusted if high trust
        if trust_level == "high" and not device.trusted_since_utc:
            device.trusted_since_utc = datetime.utcnow()
    else:
        # Create new device record
        device = TrustedDevice(
            device_id=device_id,
            trust_level=trust_level,
            total_verifications=1,
            successful_verifications=1 if verification_passed else 0,
            trusted_since_utc=datetime.utcnow() if trust_level == "high" else None
        )
        db.add(device)
    
    db.commit()
    return device


def get_device_stats(db, device_id: str):
    """Get statistics for a device"""
    device = get_trusted_device(db, device_id)
    if not device:
        return None
    
    success_rate = 0
    if device.total_verifications > 0:
        success_rate = (device.successful_verifications / device.total_verifications) * 100
    
    return {
        "device_id": device_id,
        "trust_level": device.trust_level,
        "total_verifications": device.total_verifications,
        "successful_verifications": device.successful_verifications,
        "success_rate": round(success_rate, 2),
        "first_seen": device.first_seen_utc.isoformat(),
        "last_verified": device.last_verified_utc.isoformat(),
        "trusted_since": device.trusted_since_utc.isoformat() if device.trusted_since_utc else None
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
    
    # Calculate percentages
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