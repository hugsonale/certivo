-- =============================================================================
-- CERTIVO DATABASE SCHEMA
-- =============================================================================

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- =============================================================================
-- SESSIONS TABLE
-- =============================================================================

CREATE TABLE IF NOT EXISTS sessions (
    id SERIAL PRIMARY KEY,
    session_id VARCHAR(255) UNIQUE NOT NULL,
    device_id VARCHAR(255) NOT NULL,
    trust_score FLOAT NOT NULL,
    trust_level VARCHAR(50) NOT NULL,
    total_challenges INTEGER NOT NULL,
    failed_challenges INTEGER DEFAULT 0,
    fast_track BOOLEAN DEFAULT false,
    timestamp_utc TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    INDEX idx_device_id (device_id),
    INDEX idx_timestamp (timestamp_utc),
    INDEX idx_trust_level (trust_level)
);

-- =============================================================================
-- CHALLENGE RESULTS TABLE
-- =============================================================================

CREATE TABLE IF NOT EXISTS challenge_results (
    id SERIAL PRIMARY KEY,
    session_id VARCHAR(255) NOT NULL,
    device_id VARCHAR(255) NOT NULL,
    challenge_id VARCHAR(255) UNIQUE NOT NULL,
    
    instruction TEXT NOT NULL,
    expected_direction VARCHAR(50),
    difficulty VARCHAR(50) DEFAULT 'medium',
    
    challenge_passed BOOLEAN NOT NULL,
    liveness_score FLOAT NOT NULL,
    direction_detected VARCHAR(50),
    direction_matched BOOLEAN DEFAULT false,
    
    fast_track BOOLEAN DEFAULT false,
    video_size_bytes INTEGER,
    frames_analyzed INTEGER,
    face_detected_frames INTEGER,
    
    timestamp_utc TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    INDEX idx_session_id (session_id),
    INDEX idx_device_id (device_id),
    INDEX idx_challenge_passed (challenge_passed),
    INDEX idx_timestamp (timestamp_utc)
);

-- =============================================================================
-- TRUSTED DEVICES TABLE
-- =============================================================================

CREATE TABLE IF NOT EXISTS trusted_devices (
    id SERIAL PRIMARY KEY,
    device_id VARCHAR(255) UNIQUE NOT NULL,
    
    trust_level VARCHAR(50) NOT NULL,
    total_verifications INTEGER DEFAULT 1,
    successful_verifications INTEGER DEFAULT 0,
    
    trust_revoked BOOLEAN DEFAULT false,
    revoked_at TIMESTAMP,
    revocation_reason TEXT,
    
    first_seen_utc TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_verified_utc TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    trusted_since_utc TIMESTAMP,
    
    INDEX idx_device_id (device_id),
    INDEX idx_trust_level (trust_level),
    INDEX idx_trust_revoked (trust_revoked),
    INDEX idx_last_verified (last_verified_utc)
);

-- =============================================================================
-- BOT REPORTS TABLE
-- =============================================================================

CREATE TABLE IF NOT EXISTS bot_reports (
    id SERIAL PRIMARY KEY,
    device_id VARCHAR(255) NOT NULL,
    
    bot_detected BOOLEAN NOT NULL,
    suspicion_score INTEGER NOT NULL,
    
    frontend_checks TEXT,
    fingerprint TEXT,
    backend_signals TEXT,
    
    ip_address VARCHAR(45),
    user_agent TEXT,
    
    timestamp_utc TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    INDEX idx_device_id (device_id),
    INDEX idx_bot_detected (bot_detected),
    INDEX idx_suspicion_score (suspicion_score),
    INDEX idx_timestamp (timestamp_utc)
);

-- =============================================================================
-- SUSPICIOUS DEVICES TABLE
-- =============================================================================

CREATE TABLE IF NOT EXISTS suspicious_devices (
    id SERIAL PRIMARY KEY,
    device_id VARCHAR(255) NOT NULL,
    
    reason TEXT NOT NULL,
    suspicion_score INTEGER NOT NULL,
    evidence TEXT,
    
    is_blocked BOOLEAN DEFAULT false,
    flagged_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    INDEX idx_device_id (device_id),
    INDEX idx_is_blocked (is_blocked),
    INDEX idx_suspicion_score (suspicion_score),
    INDEX idx_flagged_at (flagged_at)
);

-- =============================================================================
-- INITIAL DATA
-- =============================================================================

-- Insert test device (for development only - remove in production)
INSERT INTO trusted_devices (device_id, trust_level, total_verifications, successful_verifications)
VALUES ('test_device_001', 'high', 10, 10)
ON CONFLICT (device_id) DO NOTHING;

COMMIT;