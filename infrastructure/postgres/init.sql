-- =============================================================================
-- CERTIVO DATABASE SCHEMA - WITH CONSUMPTION TRACKING
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- =============================================================================
-- CHALLENGES TABLE (Enhanced for consumption tracking)
-- =============================================================================

CREATE TABLE IF NOT EXISTS challenges (
    id SERIAL PRIMARY KEY,
    challenge_id VARCHAR(255) UNIQUE NOT NULL,
    device_id VARCHAR(255) NOT NULL,
    template_id VARCHAR(100),
    nonce VARCHAR(255) UNIQUE NOT NULL,
    
    -- Consumption tracking
    consumed BOOLEAN DEFAULT false,
    consumed_at TIMESTAMP,
    consumed_by_device VARCHAR(255),
    consume_metadata TEXT,
    
    -- Session binding
    session_metadata TEXT,
    ip_hash VARCHAR(32),
    user_agent_hash VARCHAR(32),
    
    -- Watermark
    watermark_seed VARCHAR(64),
    
    -- Timestamps
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP NOT NULL,
    
    INDEX idx_challenge_id (challenge_id),
    INDEX idx_nonce (nonce),
    INDEX idx_consumed (consumed),
    INDEX idx_device_id (device_id),
    INDEX idx_expires_at (expires_at)
);

-- =============================================================================
-- TOKEN CONSUMPTIONS TABLE (Audit log)
-- =============================================================================

CREATE TABLE IF NOT EXISTS token_consumptions (
    id SERIAL PRIMARY KEY,
    token_id TEXT NOT NULL,
    challenge_id VARCHAR(255) NOT NULL,
    device_id VARCHAR(255) NOT NULL,
    
    -- Consumption details
    consumed_at DOUBLE PRECISION NOT NULL,
    metadata TEXT,
    
    -- Verification result
    verification_passed BOOLEAN,
    liveness_score FLOAT,
    
    -- Session info
    ip_hash VARCHAR(32),
    user_agent_hash VARCHAR(32),
    
    timestamp_utc TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    INDEX idx_token_id (token_id),
    INDEX idx_challenge_id (challenge_id),
    INDEX idx_device_id (device_id),
    INDEX idx_consumed_at (consumed_at),
    UNIQUE(token_id)  -- Ensure one consumption per token
);

-- =============================================================================
-- TAMPER ATTEMPTS TABLE (Security monitoring)
-- =============================================================================

CREATE TABLE IF NOT EXISTS tamper_attempts (
    id SERIAL PRIMARY KEY,
    
    -- Attack details
    attempted_token TEXT,
    challenge_id VARCHAR(255),
    device_id VARCHAR(255),
    
    -- Detection
    tamper_type VARCHAR(50),  -- 'signature_invalid', 'expired', 'metadata_mismatch', etc.
    detection_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    -- Context
    ip_hash VARCHAR(32),
    user_agent_hash VARCHAR(32),
    
    INDEX idx_tamper_type (tamper_type),
    INDEX idx_device_id (device_id),
    INDEX idx_detection_time (detection_time)
);

-- =============================================================================
-- REPLAY ATTEMPTS TABLE (Security monitoring)
-- =============================================================================

CREATE TABLE IF NOT EXISTS replay_attempts (
    id SERIAL PRIMARY KEY,
    
    -- Attack details
    token_id TEXT,
    challenge_id VARCHAR(255) NOT NULL,
    device_id VARCHAR(255) NOT NULL,
    
    -- Original consumption
    original_consumed_at DOUBLE PRECISION,
    
    -- Replay attempt
    replay_attempt_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    -- Context
    ip_hash VARCHAR(32),
    user_agent_hash VARCHAR(32),
    
    INDEX idx_challenge_id (challenge_id),
    INDEX idx_device_id (device_id),
    INDEX idx_replay_time (replay_attempt_time)
);

-- =============================================================================
-- EXISTING TABLES (from previous parts)
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

COMMIT;