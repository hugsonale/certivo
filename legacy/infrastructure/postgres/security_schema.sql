-- =============================================================================
-- SECURITY SCHEMA
-- Consent management, access control, and quarterly reviews
-- =============================================================================

-- Consent status enumeration
CREATE TYPE consent_status AS ENUM (
    'pending',
    'granted',
    'denied',
    'withdrawn',
    'expired'
);

-- Consent type enumeration
CREATE TYPE consent_type AS ENUM (
    'video_capture',
    'liveness_detection',
    'biometric_processing',
    'data_storage',
    'data_analysis'
);

-- Access review decision enumeration
CREATE TYPE review_decision AS ENUM (
    'approved',
    'revoked',
    'modified'
);

-- =============================================================================
-- CONSENT RECORDS
-- =============================================================================

CREATE TABLE IF NOT EXISTS consent_records (
    id SERIAL PRIMARY KEY,
    
    -- Identification
    consent_id VARCHAR(100) NOT NULL UNIQUE,
    session_id VARCHAR(100) NOT NULL,
    user_identifier VARCHAR(255),
    
    -- Consent details
    consent_types consent_type[] NOT NULL,
    purpose VARCHAR(100) NOT NULL,
    jurisdiction VARCHAR(50) NOT NULL DEFAULT 'global',
    
    -- Status
    status consent_status NOT NULL DEFAULT 'pending',
    
    -- Legal text
    consent_text TEXT NOT NULL,
    consent_version VARCHAR(20) NOT NULL DEFAULT '1.0',
    
    -- User response
    granted_at TIMESTAMP,
    denied_at TIMESTAMP,
    withdrawn_at TIMESTAMP,
    user_acknowledgment TEXT,
    denial_reason TEXT,
    withdrawal_reason TEXT,
    
    -- Metadata
    requested_at TIMESTAMP NOT NULL DEFAULT NOW(),
    ip_address INET,
    user_agent TEXT,
    
    -- Expiration
    expires_at TIMESTAMP,
    
    -- Indexes
    INDEX idx_consent_session (session_id),
    INDEX idx_consent_user (user_identifier),
    INDEX idx_consent_status (status),
    INDEX idx_consent_purpose (purpose),
    INDEX idx_consent_requested (requested_at DESC)
);

COMMENT ON TABLE consent_records IS 'Explicit consent capture for video/liveness processing';

-- =============================================================================
-- USER ACCESS (RBAC)
-- =============================================================================

CREATE TABLE IF NOT EXISTS user_access (
    id SERIAL PRIMARY KEY,
    
    -- User identification
    user_id VARCHAR(100) NOT NULL,
    user_email VARCHAR(255) NOT NULL,
    role VARCHAR(50) NOT NULL,
    
    -- Permissions (NO WILDCARDS ALLOWED)
    permissions TEXT[] NOT NULL,
    
    -- Grant details
    granted_by VARCHAR(255) NOT NULL,
    granted_at TIMESTAMP NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMP,
    
    -- Review tracking (quarterly requirement)
    last_reviewed TIMESTAMP,
    reviewed_by VARCHAR(255),
    next_review_due TIMESTAMP NOT NULL,
    review_notes TEXT,
    
    -- Justification
    business_justification TEXT NOT NULL,
    
    -- Revocation
    active BOOLEAN NOT NULL DEFAULT TRUE,
    revoked_at TIMESTAMP,
    revoked_by VARCHAR(255),
    revocation_reason TEXT,
    
    -- Constraints
    CHECK (NOT EXISTS (
        SELECT 1 FROM unnest(permissions) AS p
        WHERE p LIKE '%*%' OR p LIKE '%all%'
    )),  -- Prevent wildcard permissions
    
    -- Indexes
    INDEX idx_user_access_user (user_id),
    INDEX idx_user_access_email (user_email),
    INDEX idx_user_access_role (role),
    INDEX idx_user_access_active (active),
    INDEX idx_user_access_review (next_review_due),
    INDEX idx_user_access_expires (expires_at)
);

COMMENT ON TABLE user_access IS 'User access control with quarterly review requirement';

-- =============================================================================
-- ACCESS REVIEWS (QUARTERLY REQUIREMENT)
-- =============================================================================

CREATE TABLE IF NOT EXISTS access_reviews (
    id SERIAL PRIMARY KEY,
    
    -- Review details
    user_id VARCHAR(100) NOT NULL,
    reviewed_by VARCHAR(255) NOT NULL,
    reviewed_at TIMESTAMP NOT NULL DEFAULT NOW(),
    
    -- Decision
    decision review_decision NOT NULL,
    notes TEXT,
    
    -- Previous state
    previous_role VARCHAR(50),
    previous_permissions TEXT[],
    
    -- New state (if modified)
    new_role VARCHAR(50),
    new_permissions TEXT[],
    
    -- Indexes
    INDEX idx_access_review_user (user_id),
    INDEX idx_access_review_date (reviewed_at DESC),
    INDEX idx_access_review_decision (decision)
);

COMMENT ON TABLE access_reviews IS 'Quarterly access review audit trail';

-- =============================================================================
-- ENCRYPTION KEY AUDIT
-- =============================================================================

CREATE TABLE IF NOT EXISTS encryption_key_audit (
    id SERIAL PRIMARY KEY,
    
    -- Key details
    key_alias VARCHAR(100) NOT NULL,
    key_id VARCHAR(255) NOT NULL,
    key_type VARCHAR(50) NOT NULL,  -- database, s3, secrets
    
    -- Event
    event_type VARCHAR(50) NOT NULL,  -- created, rotated, disabled
    event_timestamp TIMESTAMP NOT NULL DEFAULT NOW(),
    performed_by VARCHAR(255),
    
    -- Metadata
    kms_region VARCHAR(50),
    rotation_enabled BOOLEAN,
    
    -- Indexes
    INDEX idx_key_audit_alias (key_alias),
    INDEX idx_key_audit_event (event_timestamp DESC),
    INDEX idx_key_audit_type (event_type)
);

COMMENT ON TABLE encryption_key_audit IS 'Audit trail for encryption key management';

-- =============================================================================
-- PURPOSE LIMITATION VIOLATIONS
-- =============================================================================

CREATE TABLE IF NOT EXISTS purpose_violations (
    id SERIAL PRIMARY KEY,
    
    -- Violation details
    user_id VARCHAR(100) NOT NULL,
    purpose VARCHAR(100) NOT NULL,
    table_name VARCHAR(100) NOT NULL,
    fields_requested TEXT[] NOT NULL,
    
    -- Violation
    disallowed_fields TEXT[] NOT NULL,
    violation_reason TEXT NOT NULL,
    
    -- Context
    occurred_at TIMESTAMP NOT NULL DEFAULT NOW(),
    ip_address INET,
    session_id VARCHAR(100),
    
    -- Resolution
    resolved BOOLEAN NOT NULL DEFAULT FALSE,
    resolved_at TIMESTAMP,
    resolved_by VARCHAR(255),
    resolution_notes TEXT,
    
    -- Indexes
    INDEX idx_purpose_violation_user (user_id),
    INDEX idx_purpose_violation_occurred (occurred_at DESC),
    INDEX idx_purpose_violation_resolved (resolved)
);

COMMENT ON TABLE purpose_violations IS 'Purpose limitation violation tracking';

-- =============================================================================
-- HELPER FUNCTIONS
-- =============================================================================

-- Function to check for wildcard permissions
CREATE OR REPLACE FUNCTION check_wildcard_permissions()
RETURNS TABLE (
    user_email VARCHAR,
    role VARCHAR,
    wildcard_permissions TEXT[]
)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    SELECT 
        ua.user_email,
        ua.role,
        ARRAY(
            SELECT p FROM unnest(ua.permissions) AS p
            WHERE p LIKE '%*%' OR p LIKE '%all%'
        ) as wildcard_permissions
    FROM user_access ua
    WHERE ua.active = TRUE
    AND EXISTS (
        SELECT 1 FROM unnest(ua.permissions) AS p
        WHERE p LIKE '%*%' OR p LIKE '%all%'
    );
END;
$$;

-- Function to get users requiring quarterly review
CREATE OR REPLACE FUNCTION get_users_requiring_review()
RETURNS TABLE (
    user_id VARCHAR,
    user_email VARCHAR,
    role VARCHAR,
    days_overdue INTEGER
)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    SELECT 
        ua.user_id,
        ua.user_email,
        ua.role,
        EXTRACT(DAY FROM NOW() - ua.next_review_due)::INTEGER as days_overdue
    FROM user_access ua
    WHERE ua.active = TRUE
    AND ua.next_review_due <= NOW()
    ORDER BY ua.next_review_due ASC;
END;
$$;

-- Function to validate consent for purpose
CREATE OR REPLACE FUNCTION validate_consent(
    p_session_id VARCHAR,
    p_purpose VARCHAR
)
RETURNS BOOLEAN
LANGUAGE plpgsql
AS $$
DECLARE
    v_valid BOOLEAN;
BEGIN
    SELECT EXISTS(
        SELECT 1
        FROM consent_records
        WHERE session_id = p_session_id
        AND purpose = p_purpose
        AND status = 'granted'
        AND (expires_at IS NULL OR expires_at > NOW())
    ) INTO v_valid;
    
    RETURN v_valid;
END;
$$;

COMMIT;