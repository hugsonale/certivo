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


-- =============================================================================
-- VERIFICATION OUTCOMES TABLE (For FAR/FRR tracking)
-- =============================================================================

CREATE TABLE IF NOT EXISTS verification_outcomes (
    id SERIAL PRIMARY KEY,
    session_id VARCHAR(255) NOT NULL,
    device_id VARCHAR(255) NOT NULL,
    
    -- Ground truth and prediction
    is_genuine BOOLEAN NOT NULL,  -- Ground truth: true genuine user
    was_accepted BOOLEAN NOT NULL,  -- System decision
    
    -- Outcome classification
    outcome_type VARCHAR(50) NOT NULL,  -- true_accept, false_reject, false_accept, true_reject
    
    -- Metrics
    liveness_score FLOAT NOT NULL,
    
    -- Metadata
    metadata TEXT,
    
    timestamp_utc TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    INDEX idx_outcome_type (outcome_type),
    INDEX idx_timestamp (timestamp_utc),
    INDEX idx_device_id (device_id)
);

-- =============================================================================
-- DEEPFAKE DETECTION RESULTS TABLE
-- =============================================================================

CREATE TABLE IF NOT EXISTS deepfake_detection_results (
    id SERIAL PRIMARY KEY,
    session_id VARCHAR(255) NOT NULL,
    device_id VARCHAR(255) NOT NULL,
    challenge_id VARCHAR(255) NOT NULL,
    
    -- Detection scores
    motion_score FLOAT,
    temporal_score FLOAT,
    anti_spoof_score FLOAT,
    av_sync_score FLOAT,
    
    -- Spoof indicators
    moire_detected BOOLEAN,
    color_temp_inconsistent BOOLEAN,
    face_warping BOOLEAN,
    
    -- Final decision
    is_spoof BOOLEAN,
    liveness_score FLOAT,
    
    timestamp_utc TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    INDEX idx_session_id (session_id),
    INDEX idx_is_spoof (is_spoof),
    INDEX idx_timestamp (timestamp_utc)
);


-- =============================================================================
-- ADMIN AUTHENTICATION AND AUTHORIZATION TABLES
-- =============================================================================

-- Admin users table
CREATE TABLE IF NOT EXISTS admin_users (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(50) UNIQUE NOT NULL,
    username VARCHAR(50) UNIQUE NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    
    -- MFA
    mfa_enabled BOOLEAN DEFAULT false,
    mfa_secret VARCHAR(255),
    backup_codes TEXT,  -- JSON array of hashed backup codes
    
    -- Status
    active BOOLEAN DEFAULT true,
    locked_out BOOLEAN DEFAULT false,
    lockout_until TIMESTAMP,
    
    -- Metadata
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(50),
    last_login TIMESTAMP,
    
    INDEX idx_username (username),
    INDEX idx_email (email),
    INDEX idx_active (active)
);

-- User roles table
CREATE TABLE IF NOT EXISTS user_roles (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(50) UNIQUE NOT NULL,
    role VARCHAR(50) NOT NULL,
    assigned_by VARCHAR(50) NOT NULL,
    assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    INDEX idx_user_id (user_id),
    INDEX idx_role (role),
    FOREIGN KEY (user_id) REFERENCES admin_users(user_id)
);

-- Admin sessions table
CREATE TABLE IF NOT EXISTS admin_sessions (
    id SERIAL PRIMARY KEY,
    session_token VARCHAR(255) UNIQUE NOT NULL,
    user_id VARCHAR(50) NOT NULL,
    
    -- Session metadata
    ip_address_hash VARCHAR(32),
    user_agent_hash VARCHAR(32),
    mfa_verified BOOLEAN NOT NULL,
    
    -- Lifecycle
    created_at TIMESTAMP NOT NULL,
    expires_at TIMESTAMP NOT NULL,
    revoked BOOLEAN DEFAULT false,
    revoked_at TIMESTAMP,
    
    INDEX idx_session_token (session_token),
    INDEX idx_user_id (user_id),
    INDEX idx_created_at (created_at),
    FOREIGN KEY (user_id) REFERENCES admin_users(user_id)
);

-- Audit logs table (immutable)
CREATE TABLE IF NOT EXISTS audit_logs (
    id SERIAL PRIMARY KEY,
    
    -- Action details
    action VARCHAR(100) NOT NULL,
    actor_id VARCHAR(50) NOT NULL,
    actor_ip_hash VARCHAR(32),
    target_resource VARCHAR(255),
    details TEXT,  -- JSON
    result VARCHAR(20) NOT NULL,  -- success, failure
    
    -- Timestamp
    timestamp_utc TIMESTAMP NOT NULL,
    
    -- Hash chain for integrity
    previous_hash VARCHAR(64),
    hash VARCHAR(64) NOT NULL,
    
    INDEX idx_action (action),
    INDEX idx_actor_id (actor_id),
    INDEX idx_timestamp (timestamp_utc),
    INDEX idx_target_resource (target_resource)
);

-- Note: NO UPDATE or DELETE operations allowed on audit_logs
-- Enforce via database permissions

-- =============================================================================
-- SECURITY: Revoke UPDATE/DELETE on audit_logs
-- =============================================================================

REVOKE UPDATE, DELETE ON audit_logs FROM certivo;
GRANT INSERT, SELECT ON audit_logs TO certivo;

-- =============================================================================
-- KEY ROTATION TRACKING TABLE
-- =============================================================================

CREATE TABLE IF NOT EXISTS key_rotations (
    id SERIAL PRIMARY KEY,
    
    -- Key details
    key_type VARCHAR(50) NOT NULL,  -- database_password, api_key, session_secret, etc.
    key_name VARCHAR(255) NOT NULL,  -- production/database/password
    
    -- Rotation status
    status VARCHAR(20) NOT NULL,  -- pending, in_progress, completed, failed, rolled_back
    
    -- Error information
    error TEXT,
    
    -- Metadata
    metadata JSONB,
    
    -- Timestamp
    rotated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    INDEX idx_key_type (key_type),
    INDEX idx_key_name (key_name),
    INDEX idx_status (status),
    INDEX idx_rotated_at (rotated_at)
);

-- =============================================================================
-- SECRET ACCESS AUDIT TABLE
-- =============================================================================

CREATE TABLE IF NOT EXISTS secret_access_audit (
    id SERIAL PRIMARY KEY,
    
    -- Access details
    secret_name VARCHAR(255) NOT NULL,
    service_name VARCHAR(100) NOT NULL,
    
    -- Context
    access_type VARCHAR(20) NOT NULL,  -- read, write, rotate
    
    -- Result
    success BOOLEAN NOT NULL,
    error TEXT,
    
    -- Timestamp
    accessed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    INDEX idx_secret_name (secret_name),
    INDEX idx_service_name (service_name),
    INDEX idx_accessed_at (accessed_at)
);

COMMIT;