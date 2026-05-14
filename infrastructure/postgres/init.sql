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



-- =============================================================================
-- RED-TEAM TESTING TABLES
-- =============================================================================

-- Attack results table
CREATE TABLE IF NOT EXISTS red_team_attacks (
    id SERIAL PRIMARY KEY,
    
    -- Attack details
    attack_type VARCHAR(50) NOT NULL,
    success BOOLEAN NOT NULL,
    confidence FLOAT NOT NULL,
    bypass_rate FLOAT NOT NULL,
    
    -- Details (JSON)
    details JSONB,
    
    -- Severity
    severity VARCHAR(10),  -- P0, P1, P2, P3
    
    -- Timestamp
    timestamp TIMESTAMP NOT NULL,
    
    INDEX idx_attack_type (attack_type),
    INDEX idx_timestamp (timestamp),
    INDEX idx_severity (severity)
);

-- Findings table
CREATE TABLE IF NOT EXISTS red_team_findings (
    id SERIAL PRIMARY KEY,
    
    -- Finding identification
    finding_id VARCHAR(50) UNIQUE NOT NULL,
    title VARCHAR(255) NOT NULL,
    severity VARCHAR(10) NOT NULL,  -- P0, P1, P2, P3
    attack_type VARCHAR(50) NOT NULL,
    
    -- Description
    description TEXT NOT NULL,
    impact TEXT NOT NULL,
    reproduction_steps JSONB NOT NULL,
    affected_components JSONB NOT NULL,
    
    -- Metrics
    bypass_rate FLOAT NOT NULL,
    
    -- Discovery
    discovered_at TIMESTAMP NOT NULL,
    discovered_by VARCHAR(100) NOT NULL,
    
    -- Assignment
    assigned_to VARCHAR(100),
    assigned_at TIMESTAMP,
    assigned_by VARCHAR(100),
    
    -- SLA
    sla_deadline TIMESTAMP NOT NULL,
    escalation_time TIMESTAMP NOT NULL,
    time_remaining_hours FLOAT,
    
    -- Status
    status VARCHAR(20) NOT NULL DEFAULT 'open',
    sla_status VARCHAR(20) NOT NULL DEFAULT 'on_track',
    
    -- Resolution
    closed_at TIMESTAMP,
    resolution_hours FLOAT,
    remediation_notes TEXT,
    
    -- Metadata
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_by VARCHAR(100),
    
    INDEX idx_finding_id (finding_id),
    INDEX idx_severity (severity),
    INDEX idx_status (status),
    INDEX idx_sla_status (sla_status),
    INDEX idx_sla_deadline (sla_deadline),
    INDEX idx_assigned_to (assigned_to)
);

-- Finding status history
CREATE TABLE IF NOT EXISTS finding_status_history (
    id SERIAL PRIMARY KEY,
    
    finding_id VARCHAR(50) NOT NULL,
    old_status VARCHAR(20),
    new_status VARCHAR(20) NOT NULL,
    changed_by VARCHAR(100) NOT NULL,
    notes TEXT,
    changed_at TIMESTAMP NOT NULL,
    
    INDEX idx_finding_id (finding_id),
    INDEX idx_changed_at (changed_at),
    FOREIGN KEY (finding_id) REFERENCES red_team_findings(finding_id)
);

-- Risk gate validation results
CREATE TABLE IF NOT EXISTS risk_gate_validations (
    id SERIAL PRIMARY KEY,
    
    -- Test run
    test_run_id VARCHAR(50) NOT NULL,
    
    -- Results
    weighted_bypass_score FLOAT NOT NULL,
    threshold FLOAT NOT NULL,
    passed BOOLEAN NOT NULL,
    
    -- Attack results (JSON)
    attack_results JSONB NOT NULL,
    
    -- Findings
    findings_count INTEGER NOT NULL,
    p0_count INTEGER NOT NULL,
    p1_count INTEGER NOT NULL,
    
    -- Timestamp
    validated_at TIMESTAMP NOT NULL,
    
    INDEX idx_test_run_id (test_run_id),
    INDEX idx_validated_at (validated_at),
    INDEX idx_passed (passed)
);


-- =============================================================================
-- CHALLENGE DESIGN TABLES
-- =============================================================================

-- Challenge completion tracking
CREATE TABLE IF NOT EXISTS challenge_completion_tracking (
    id SERIAL PRIMARY KEY,
    
    -- Challenge details
    challenge_id VARCHAR(100) NOT NULL,
    template_id VARCHAR(50) NOT NULL,
    user_id VARCHAR(100) NOT NULL,
    
    -- Completion status
    status VARCHAR(20) NOT NULL,  -- completed, failed, abandoned, timeout
    duration_seconds FLOAT NOT NULL,
    
    -- Cohort tracking
    is_pilot_user BOOLEAN DEFAULT false,
    
    -- Accessibility
    accessibility_profile JSONB,
    
    -- Failure analysis
    failure_reason VARCHAR(255),
    
    -- Timestamp
    attempted_at TIMESTAMP NOT NULL,
    
    INDEX idx_template_id (template_id),
    INDEX idx_status (status),
    INDEX idx_is_pilot_user (is_pilot_user),
    INDEX idx_attempted_at (attempted_at),
    INDEX idx_user_id (user_id)
);

-- Challenge templates metadata
CREATE TABLE IF NOT EXISTS challenge_templates_metadata (
    id SERIAL PRIMARY KEY,
    
    template_id VARCHAR(50) UNIQUE NOT NULL,
    name VARCHAR(255) NOT NULL,
    challenge_type VARCHAR(50) NOT NULL,
    difficulty VARCHAR(20) NOT NULL,
    
    -- Accessibility
    requires_motion BOOLEAN NOT NULL,
    requires_vision BOOLEAN NOT NULL,
    requires_audio BOOLEAN NOT NULL,
    
    -- Metrics
    entropy_bits FLOAT NOT NULL,
    estimated_duration_seconds FLOAT NOT NULL,
    
    -- Status
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    INDEX idx_template_id (template_id),
    INDEX idx_is_active (is_active)
);

-- =============================================================================
-- SESSION CONTROL TABLES
-- =============================================================================

-- Verification sessions
CREATE TABLE IF NOT EXISTS verification_sessions (
    id SERIAL PRIMARY KEY,
    
    -- Session identification
    session_id VARCHAR(100) UNIQUE NOT NULL,
    device_id VARCHAR(100) NOT NULL,
    ip_address VARCHAR(45) NOT NULL,
    challenge_id VARCHAR(100) NOT NULL,
    
    -- Status
    status VARCHAR(20) NOT NULL DEFAULT 'active',
    
    -- Attempt tracking
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    
    -- Timing (server time authority)
    created_at TIMESTAMP NOT NULL,
    challenge_expires_at TIMESTAMP NOT NULL,
    session_expires_at TIMESTAMP NOT NULL,
    last_attempt_at TIMESTAMP,
    next_retry_allowed_at TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    -- Expiry tracking
    expired_reason VARCHAR(100),
    
    INDEX idx_session_id (session_id),
    INDEX idx_device_id (device_id),
    INDEX idx_ip_address (ip_address),
    INDEX idx_status (status),
    INDEX idx_created_at (created_at),
    INDEX idx_challenge_expires_at (challenge_expires_at),
    INDEX idx_session_expires_at (session_expires_at)
);

-- Session attempt history
CREATE TABLE IF NOT EXISTS session_attempt_history (
    id SERIAL PRIMARY KEY,
    
    session_id VARCHAR(100) NOT NULL,
    attempt_number INTEGER NOT NULL,
    success BOOLEAN NOT NULL,
    attempted_at TIMESTAMP NOT NULL,
    
    -- Additional metadata
    device_id VARCHAR(100),
    ip_address VARCHAR(45),
    
    INDEX idx_session_id (session_id),
    INDEX idx_attempted_at (attempted_at),
    INDEX idx_device_id (device_id),
    INDEX idx_ip_address (ip_address),
    FOREIGN KEY (session_id) REFERENCES verification_sessions(session_id)
);

-- Abuse incidents
CREATE TABLE IF NOT EXISTS abuse_incidents (
    id SERIAL PRIMARY KEY,
    
    pattern VARCHAR(50) NOT NULL,
    severity VARCHAR(20) NOT NULL,
    count INTEGER NOT NULL,
    affected_entities TEXT[],
    
    first_seen TIMESTAMP NOT NULL,
    last_seen TIMESTAMP NOT NULL,
    detected_at TIMESTAMP NOT NULL,
    
    -- Resolution
    resolved BOOLEAN DEFAULT false,
    resolved_at TIMESTAMP,
    resolution_notes TEXT,
    
    INDEX idx_pattern (pattern),
    INDEX idx_severity (severity),
    INDEX idx_detected_at (detected_at),
    INDEX idx_resolved (resolved)
);


-- =============================================================================
-- RISK SCORING AND POLICY TABLES
-- =============================================================================

-- Risk policies
CREATE TABLE IF NOT EXISTS risk_policies (
    id SERIAL PRIMARY KEY,
    
    -- Policy identification
    policy_id VARCHAR(100) UNIQUE NOT NULL,
    customer_id VARCHAR(100) NOT NULL,
    policy_name VARCHAR(255) NOT NULL,
    
    -- Thresholds
    approve_threshold DECIMAL(5,4) NOT NULL,  -- e.g., 0.3000
    review_threshold DECIMAL(5,4) NOT NULL,   -- e.g., 0.5000
    deny_threshold DECIMAL(5,4) NOT NULL,     -- e.g., 0.7500
    
    -- Factor weights (JSON)
    factor_weights JSONB NOT NULL,
    
    -- Custom rules (JSON)
    custom_rules JSONB DEFAULT '{}',
    
    -- Versioning
    version INTEGER NOT NULL DEFAULT 1,
    is_active BOOLEAN DEFAULT true,
    
    -- Metadata
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL,
    created_by VARCHAR(100) NOT NULL,
    updated_by VARCHAR(100),
    
    INDEX idx_policy_id (policy_id),
    INDEX idx_customer_id (customer_id),
    INDEX idx_is_active (is_active)
);

-- Policy change log
CREATE TABLE IF NOT EXISTS policy_change_log (
    id SERIAL PRIMARY KEY,
    
    policy_id VARCHAR(100) NOT NULL,
    customer_id VARCHAR(100) NOT NULL,
    old_version INTEGER NOT NULL,
    new_version INTEGER NOT NULL,
    
    -- Changes (JSON)
    changes JSONB NOT NULL,
    
    -- Metadata
    changed_by VARCHAR(100) NOT NULL,
    changed_at TIMESTAMP NOT NULL,
    
    INDEX idx_policy_id (policy_id),
    INDEX idx_changed_at (changed_at)
);

-- Risk assessments
CREATE TABLE IF NOT EXISTS risk_assessments (
    id SERIAL PRIMARY KEY,
    
    -- Session context
    session_id VARCHAR(100) NOT NULL,
    device_id VARCHAR(100) NOT NULL,
    customer_id VARCHAR(100) NOT NULL,
    
    -- Assessment results
    overall_risk_score DECIMAL(5,4) NOT NULL,
    risk_level VARCHAR(20) NOT NULL,
    decision VARCHAR(20) NOT NULL,
    passed BOOLEAN NOT NULL,
    
    -- Factor scores (JSON)
    factor_scores JSONB NOT NULL,
    
    -- Policy context
    policy_id VARCHAR(100) NOT NULL,
    policy_version INTEGER NOT NULL,
    threshold_used DECIMAL(5,4) NOT NULL,
    
    -- Timestamp
    assessed_at TIMESTAMP NOT NULL,
    
    INDEX idx_session_id (session_id),
    INDEX idx_device_id (device_id),
    INDEX idx_customer_id (customer_id),
    INDEX idx_decision (decision),
    INDEX idx_assessed_at (assessed_at)
);

-- Explainability records
CREATE TABLE IF NOT EXISTS explainability_records (
    id SERIAL PRIMARY KEY,
    
    -- Record identification
    record_id VARCHAR(100) UNIQUE NOT NULL,
    session_id VARCHAR(100) NOT NULL,
    device_id VARCHAR(100) NOT NULL,
    customer_id VARCHAR(100) NOT NULL,
    
    -- Decision details
    decision VARCHAR(20) NOT NULL,
    overall_risk_score DECIMAL(5,4) NOT NULL,
    threshold_used DECIMAL(5,4) NOT NULL,
    passed BOOLEAN NOT NULL,
    
    -- Factor breakdown (JSON)
    factor_scores JSONB NOT NULL,
    
    -- Explanations
    summary_explanation TEXT NOT NULL,
    detailed_explanation TEXT NOT NULL,
    technical_details JSONB NOT NULL,
    
    -- Primary concerns
    primary_concerns TEXT[],
    
    -- Policy context
    policy_id VARCHAR(100) NOT NULL,
    policy_version INTEGER NOT NULL,
    
    -- Timestamp
    timestamp TIMESTAMP NOT NULL,
    
    INDEX idx_record_id (record_id),
    INDEX idx_session_id (session_id),
    INDEX idx_device_id (device_id),
    INDEX idx_customer_id (customer_id),
    INDEX idx_decision (decision),
    INDEX idx_timestamp (timestamp)
);

-- =============================================================================
-- SLO MONITORING TABLES
-- =============================================================================

-- API request metrics
CREATE TABLE IF NOT EXISTS api_requests (
    id BIGSERIAL PRIMARY KEY,
    
    endpoint VARCHAR(255) NOT NULL,
    status_code INTEGER NOT NULL,
    duration_ms DECIMAL(10,3) NOT NULL,
    success BOOLEAN NOT NULL,
    timestamp TIMESTAMP NOT NULL,
    
    INDEX idx_endpoint (endpoint),
    INDEX idx_timestamp (timestamp),
    INDEX idx_success (success)
);

-- Partition by month for performance
CREATE TABLE IF NOT EXISTS api_requests_2025_01 PARTITION OF api_requests
FOR VALUES FROM ('2025-01-01') TO ('2025-02-01');

CREATE TABLE IF NOT EXISTS api_requests_2025_02 PARTITION OF api_requests
FOR VALUES FROM ('2025-02-01') TO ('2025-03-01');

-- Challenge issuance metrics
CREATE TABLE IF NOT EXISTS challenge_issuance_metrics (
    id BIGSERIAL PRIMARY KEY,
    
    challenge_id VARCHAR(100) NOT NULL,
    duration_ms DECIMAL(10,3) NOT NULL,
    success BOOLEAN NOT NULL,
    timestamp TIMESTAMP NOT NULL,
    
    INDEX idx_challenge_id (challenge_id),
    INDEX idx_timestamp (timestamp),
    INDEX idx_success (success)
);

-- Verify accept metrics
CREATE TABLE IF NOT EXISTS verify_accept_metrics (
    id BIGSERIAL PRIMARY KEY,
    
    session_id VARCHAR(100) NOT NULL,
    duration_ms DECIMAL(10,3) NOT NULL,
    upload_duration_ms DECIMAL(10,3) NOT NULL,
    processing_duration_ms DECIMAL(10,3) NOT NULL,
    success BOOLEAN NOT NULL,
    timestamp TIMESTAMP NOT NULL,
    
    INDEX idx_session_id (session_id),
    INDEX idx_timestamp (timestamp),
    INDEX idx_success (success)
);

-- Queue processing metrics
CREATE TABLE IF NOT EXISTS queue_processing_metrics (
    id BIGSERIAL PRIMARY KEY,
    
    job_id VARCHAR(100) NOT NULL,
    queue_name VARCHAR(50) NOT NULL,
    queued_at TIMESTAMP NOT NULL,
    started_at TIMESTAMP NOT NULL,
    completed_at TIMESTAMP NOT NULL,
    delay_ms DECIMAL(10,3) NOT NULL,
    processing_ms DECIMAL(10,3) NOT NULL,
    
    INDEX idx_job_id (job_id),
    INDEX idx_queue_name (queue_name),
    INDEX idx_queued_at (queued_at)
);

-- SLO breach incidents
CREATE TABLE IF NOT EXISTS slo_breach_incidents (
    id SERIAL PRIMARY KEY,
    
    metric VARCHAR(50) NOT NULL,
    target_value DECIMAL(10,3) NOT NULL,
    actual_value DECIMAL(10,3) NOT NULL,
    breach_percentage DECIMAL(5,2) NOT NULL,
    
    time_window VARCHAR(50) NOT NULL,
    samples INTEGER NOT NULL,
    
    detected_at TIMESTAMP NOT NULL,
    resolved_at TIMESTAMP,
    
    -- Incident details
    root_cause TEXT,
    remediation_notes TEXT,
    
    INDEX idx_metric (metric),
    INDEX idx_detected_at (detected_at),
    INDEX idx_resolved_at (resolved_at)
);


COMMIT;