"""
Unit tests for database.py
Tests database operations and data integrity
"""

import pytest
from datetime import datetime, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from database import (
    Base, SessionRecord, ChallengeResult, TrustedDevice, ActiveChallenge,
    store_challenge, get_challenge, delete_challenge,
    store_challenge_result, get_session_results,
    store_session, get_session,
    is_device_trusted, update_device_trust, revoke_device_trust,
    get_device_stats
)


# ============================================================================
# TEST DATABASE SETUP
# ============================================================================

@pytest.fixture
def test_db():
    """Create a test database in memory"""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    
    yield db
    
    db.close()


# ============================================================================
# CHALLENGE OPERATIONS TESTS
# ============================================================================

def test_store_and_retrieve_challenge(test_db):
    """Should store and retrieve challenge"""
    challenge = store_challenge(
        db=test_db,
        challenge_id="test_challenge_1",
        device_id="test_device",
        instruction="Turn left",
        expected_direction="left",
        token_id="test_token",
        expires_at=datetime.utcnow() + timedelta(minutes=5),
        difficulty="medium"
    )
    
    assert challenge.challenge_id == "test_challenge_1"
    
    retrieved = get_challenge(test_db, "test_challenge_1")
    assert retrieved is not None
    assert retrieved.instruction == "Turn left"


def test_delete_challenge(test_db):
    """Should delete challenge"""
    store_challenge(
        db=test_db,
        challenge_id="test_challenge_2",
        device_id="test_device",
        instruction="Turn right",
        expected_direction="right",
        token_id="test_token",
        expires_at=datetime.utcnow() + timedelta(minutes=5)
    )
    
    success = delete_challenge(test_db, "test_challenge_2")
    assert success == True
    
    retrieved = get_challenge(test_db, "test_challenge_2")
    assert retrieved is None


# ============================================================================
# CHALLENGE RESULT TESTS
# ============================================================================

def test_store_challenge_result(test_db):
    """Should store challenge result"""
    result = store_challenge_result(
        db=test_db,
        session_id="session_1",
        device_id="device_1",
        challenge_id="challenge_1",
        instruction="Turn left",
        expected_direction="left",
        challenge_passed=True,
        liveness_score=0.95,
        direction_detected="left",
        direction_matched=True,
        fast_track=False,
        video_size_bytes=50000
    )
    
    assert result.challenge_passed == True
    assert result.liveness_score == 0.95


def test_get_session_results(test_db):
    """Should retrieve all results for a device session"""
    device_id = "device_test"
    
    # Store multiple results
    for i in range(3):
        store_challenge_result(
            db=test_db,
            session_id=f"session_{i}",
            device_id=device_id,
            challenge_id=f"challenge_{i}",
            instruction="Test",
            expected_direction="left",
            challenge_passed=True,
            liveness_score=0.9,
            direction_detected="left",
            direction_matched=True
        )
    
    results = get_session_results(test_db, device_id)
    assert len(results) == 3


# ============================================================================
# SESSION TESTS
# ============================================================================

def test_store_and_retrieve_session(test_db):
    """Should store and retrieve session"""
    session = store_session(
        db=test_db,
        session_id="session_test_1",
        device_id="device_1",
        trust_score=85.0,
        trust_level="high",
        failed_challenges=0,
        total_challenges=2,
        fast_track=False
    )
    
    assert session.trust_score == 85.0
    
    retrieved = get_session(test_db, "session_test_1")
    assert retrieved is not None
    assert retrieved.trust_level == "high"


# ============================================================================
# TRUSTED DEVICE TESTS
# ============================================================================

def test_device_trust_workflow(test_db):
    """Should handle complete trust workflow"""
    device_id = "device_trust_test"
    
    # Initially not trusted
    assert is_device_trusted(test_db, device_id) == False
    
    # Update to high trust
    update_device_trust(
        db=test_db,
        device_id=device_id,
        trust_level="high",
        verification_passed=True
    )
    
    # Now should be trusted
    assert is_device_trusted(test_db, device_id) == True
    
    # Revoke trust
    revoke_device_trust(test_db, device_id, reason="Test revocation")
    
    # Should no longer be trusted
    assert is_device_trusted(test_db, device_id) == False


def test_device_stats(test_db):
    """Should calculate device statistics"""
    device_id = "device_stats_test"
    
    # Create device with some verifications
    update_device_trust(
        db=test_db,
        device_id=device_id,
        trust_level="high",
        verification_passed=True
    )
    
    stats = get_device_stats(test_db, device_id)
    
    assert stats is not None
    assert stats['device_id'] == device_id
    assert stats['trust_level'] == "high"
    assert 'success_rate' in stats


# ============================================================================
# EDGE CASES
# ============================================================================

def test_nonexistent_challenge(test_db):
    """Should return None for non-existent challenge"""
    result = get_challenge(test_db, "does_not_exist")
    assert result is None


def test_nonexistent_session(test_db):
    """Should return None for non-existent session"""
    result = get_session(test_db, "does_not_exist")
    assert result is None


def test_empty_session_results(test_db):
    """Should return empty list for device with no results"""
    results = get_session_results(test_db, "new_device")
    assert len(results) == 0