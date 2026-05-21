-- =============================================================================
-- DATA CLASSIFICATION SCHEMA
-- Stores data classification metadata and audit logs
-- =============================================================================

-- Data classification levels enumeration
CREATE TYPE data_classification_level AS ENUM (
    'public',
    'internal',
    'sensitive',
    'biometric_adjacent'
);

-- Retention policy enumeration
CREATE TYPE retention_policy_type AS ENUM (
    'short_term',    -- 7 days
    'medium_term',   -- 90 days
    'long_term',     -- 7 years
    'indefinite'     -- No automatic deletion
);

-- Data inventory master table
CREATE TABLE IF NOT EXISTS data_inventory (
    id SERIAL PRIMARY KEY,
    
    -- Table identification
    table_name VARCHAR(100) NOT NULL,
    database_name VARCHAR(100) NOT NULL,
    schema_name VARCHAR(100) NOT NULL,
    
    -- Ownership
    data_owner VARCHAR(255) NOT NULL,
    technical_owner VARCHAR(255) NOT NULL,
    business_unit VARCHAR(100) NOT NULL,
    
    -- Purpose
    purpose TEXT NOT NULL,
    legal_basis TEXT,
    
    -- Classification
    highest_classification data_classification_level NOT NULL,
    
    -- Security
    encryption_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    access_controls TEXT[],
    
    -- Compliance
    contains_pii BOOLEAN NOT NULL DEFAULT FALSE,
    contains_phi BOOLEAN NOT NULL DEFAULT FALSE,
    gdpr_applicable BOOLEAN NOT NULL DEFAULT FALSE,
    ccpa_applicable BOOLEAN NOT NULL DEFAULT FALSE,
    
    -- Retention
    default_retention_policy retention_policy_type NOT NULL,
    retention_days INTEGER,
    
    -- Audit
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    last_updated TIMESTAMP NOT NULL DEFAULT NOW(),
    last_reviewed TIMESTAMP NOT NULL DEFAULT NOW(),
    reviewed_by VARCHAR(255),
    
    -- Constraints
    UNIQUE(database_name, schema_name, table_name),
    
    -- Indexes
    INDEX idx_data_inventory_table (table_name),
    INDEX idx_data_inventory_owner (data_owner),
    INDEX idx_data_inventory_classification (highest_classification),
    INDEX idx_data_inventory_pii (contains_pii),
    INDEX idx_data_inventory_reviewed (last_reviewed)
);

-- Field classification details
CREATE TABLE IF NOT EXISTS field_classifications (
    id SERIAL PRIMARY KEY,
    
    -- Field identification
    data_inventory_id INTEGER NOT NULL REFERENCES data_inventory(id) ON DELETE CASCADE,
    field_name VARCHAR(100) NOT NULL,
    
    -- Classification
    classification data_classification_level NOT NULL,
    description TEXT NOT NULL,
    data_type VARCHAR(100) NOT NULL,
    
    -- Ownership
    owner VARCHAR(255) NOT NULL,
    business_unit VARCHAR(100) NOT NULL,
    
    -- Retention
    retention_policy retention_policy_type NOT NULL,
    retention_days INTEGER,
    
    -- Regulatory
    pii BOOLEAN NOT NULL DEFAULT FALSE,
    phi BOOLEAN NOT NULL DEFAULT FALSE,
    gdpr_applicable BOOLEAN NOT NULL DEFAULT FALSE,
    ccpa_applicable BOOLEAN NOT NULL DEFAULT FALSE,
    
    -- Security
    encryption_required BOOLEAN NOT NULL DEFAULT FALSE,
    encryption_at_rest BOOLEAN NOT NULL DEFAULT FALSE,
    encryption_in_transit BOOLEAN NOT NULL DEFAULT FALSE,
    access_logging_required BOOLEAN NOT NULL DEFAULT FALSE,
    
    -- Usage
    purpose TEXT NOT NULL,
    legal_basis TEXT,
    
    -- Audit
    last_reviewed TIMESTAMP NOT NULL DEFAULT NOW(),
    reviewed_by VARCHAR(255),
    
    -- Constraints
    UNIQUE(data_inventory_id, field_name),
    
    -- Indexes
    INDEX idx_field_class_inventory (data_inventory_id),
    INDEX idx_field_class_name (field_name),
    INDEX idx_field_class_level (classification),
    INDEX idx_field_class_pii (pii)
);

-- Data access audit log
CREATE TABLE IF NOT EXISTS data_access_log (
    id BIGSERIAL PRIMARY KEY,
    
    -- Access details
    table_name VARCHAR(100) NOT NULL,
    field_name VARCHAR(100),
    
    -- User details
    user_id VARCHAR(100) NOT NULL,
    user_email VARCHAR(255),
    user_role VARCHAR(100),
    
    -- Access type
    access_type VARCHAR(50) NOT NULL,  -- SELECT, INSERT, UPDATE, DELETE
    access_reason TEXT,
    
    -- Context
    ip_address INET,
    user_agent TEXT,
    session_id VARCHAR(100),
    
    -- Timestamp
    accessed_at TIMESTAMP NOT NULL DEFAULT NOW(),
    
    -- Indexes
    INDEX idx_access_log_table (table_name),
    INDEX idx_access_log_user (user_id),
    INDEX idx_access_log_timestamp (accessed_at DESC),
    INDEX idx_access_log_type (access_type)
);

-- Partition by month for performance
CREATE TABLE IF NOT EXISTS data_access_log_2025_05 PARTITION OF data_access_log
FOR VALUES FROM ('2025-05-01') TO ('2025-06-01');

CREATE TABLE IF NOT EXISTS data_access_log_2025_06 PARTITION OF data_access_log
FOR VALUES FROM ('2025-06-01') TO ('2025-07-01');

-- Data retention execution log
CREATE TABLE IF NOT EXISTS data_retention_log (
    id SERIAL PRIMARY KEY,
    
    -- Retention execution details
    table_name VARCHAR(100) NOT NULL,
    retention_policy retention_policy_type NOT NULL,
    
    -- Execution
    records_evaluated INTEGER NOT NULL,
    records_deleted INTEGER NOT NULL,
    execution_duration_ms DECIMAL(10,3),
    
    -- Status
    status VARCHAR(50) NOT NULL,  -- success, failed, partial
    error_message TEXT,
    
    -- Timestamp
    executed_at TIMESTAMP NOT NULL DEFAULT NOW(),
    executed_by VARCHAR(255) NOT NULL,
    
    -- Indexes
    INDEX idx_retention_log_table (table_name),
    INDEX idx_retention_log_executed (executed_at DESC)
);

-- Data classification review schedule
CREATE TABLE IF NOT EXISTS classification_review_schedule (
    id SERIAL PRIMARY KEY,
    
    -- Table to review
    data_inventory_id INTEGER NOT NULL REFERENCES data_inventory(id) ON DELETE CASCADE,
    
    -- Review schedule
    review_frequency_days INTEGER NOT NULL DEFAULT 365,  -- Annual by default
    next_review_date DATE NOT NULL,
    
    -- Assigned reviewer
    assigned_to VARCHAR(255) NOT NULL,
    
    -- Status
    status VARCHAR(50) NOT NULL DEFAULT 'pending',  -- pending, in_progress, completed
    
    -- Timestamps
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    
    -- Indexes
    INDEX idx_review_schedule_next (next_review_date),
    INDEX idx_review_schedule_assigned (assigned_to),
    INDEX idx_review_schedule_status (status)
);

-- Data breach incident tracking (for compliance)
CREATE TABLE IF NOT EXISTS data_breach_incidents (
    id SERIAL PRIMARY KEY,
    
    -- Incident details
    incident_id VARCHAR(100) NOT NULL UNIQUE,
    severity VARCHAR(50) NOT NULL,  -- low, medium, high, critical
    
    -- Affected data
    affected_tables TEXT[],
    affected_fields TEXT[],
    classification_levels data_classification_level[],
    
    -- Impact
    records_affected INTEGER,
    contains_pii BOOLEAN NOT NULL DEFAULT FALSE,
    contains_phi BOOLEAN NOT NULL DEFAULT FALSE,
    
    -- Response
    detected_at TIMESTAMP NOT NULL,
    reported_at TIMESTAMP,
    contained_at TIMESTAMP,
    resolved_at TIMESTAMP,
    
    -- Details
    description TEXT NOT NULL,
    root_cause TEXT,
    remediation_actions TEXT,
    
    -- Notification
    customers_notified BOOLEAN NOT NULL DEFAULT FALSE,
    regulators_notified BOOLEAN NOT NULL DEFAULT FALSE,
    notification_date TIMESTAMP,
    
    -- Owner
    incident_owner VARCHAR(255) NOT NULL,
    
    -- Timestamps
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    
    -- Indexes
    INDEX idx_breach_incident_id (incident_id),
    INDEX idx_breach_severity (severity),
    INDEX idx_breach_detected (detected_at DESC)
);

-- Data subject access requests (GDPR/CCPA)
CREATE TABLE IF NOT EXISTS data_subject_requests (
    id SERIAL PRIMARY KEY,
    
    -- Request details
    request_id VARCHAR(100) NOT NULL UNIQUE,
    request_type VARCHAR(50) NOT NULL,  -- access, deletion, portability, correction
    
    -- Subject details (hashed/encrypted)
    subject_identifier_hash VARCHAR(64) NOT NULL,  -- SHA256 of email/ID
    
    -- Status
    status VARCHAR(50) NOT NULL DEFAULT 'pending',
    
    -- Processing
    requested_at TIMESTAMP NOT NULL,
    acknowledged_at TIMESTAMP,
    completed_at TIMESTAMP,
    deadline TIMESTAMP NOT NULL,
    
    -- Affected data
    tables_accessed TEXT[],
    records_found INTEGER,
    
    -- Actions taken
    data_exported BOOLEAN NOT NULL DEFAULT FALSE,
    data_deleted BOOLEAN NOT NULL DEFAULT FALSE,
    data_corrected BOOLEAN NOT NULL DEFAULT FALSE,
    
    -- Details
    request_source VARCHAR(100),  -- email, web_form, phone
    notes TEXT,
    
    -- Assigned
    assigned_to VARCHAR(255),
    
    -- Timestamps
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    
    -- Indexes
    INDEX idx_dsr_request_id (request_id),
    INDEX idx_dsr_status (status),
    INDEX idx_dsr_deadline (deadline),
    INDEX idx_dsr_type (request_type)
);

COMMIT;

-- =============================================================================
-- FUNCTIONS FOR DATA CLASSIFICATION
-- =============================================================================

-- Function to get classification for a field
CREATE OR REPLACE FUNCTION get_field_classification(
    p_table_name VARCHAR,
    p_field_name VARCHAR
)
RETURNS data_classification_level
LANGUAGE plpgsql
AS $$
DECLARE
    v_classification data_classification_level;
BEGIN
    SELECT fc.classification INTO v_classification
    FROM field_classifications fc
    JOIN data_inventory di ON fc.data_inventory_id = di.id
    WHERE di.table_name = p_table_name
    AND fc.field_name = p_field_name;
    
    RETURN v_classification;
END;
$$;

-- Function to log data access
CREATE OR REPLACE FUNCTION log_data_access(
    p_table_name VARCHAR,
    p_field_name VARCHAR,
    p_user_id VARCHAR,
    p_access_type VARCHAR
)
RETURNS VOID
LANGUAGE plpgsql
AS $$
BEGIN
    INSERT INTO data_access_log (
        table_name,
        field_name,
        user_id,
        access_type
    ) VALUES (
        p_table_name,
        p_field_name,
        p_user_id,
        p_access_type
    );
END;
$$;

-- Function to check if review is overdue
CREATE OR REPLACE FUNCTION get_overdue_reviews()
RETURNS TABLE (
    table_name VARCHAR,
    last_reviewed TIMESTAMP,
    days_overdue INTEGER,
    assigned_to VARCHAR
)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    SELECT 
        di.table_name,
        di.last_reviewed,
        EXTRACT(DAY FROM NOW() - di.last_reviewed)::INTEGER as days_overdue,
        crs.assigned_to
    FROM data_inventory di
    JOIN classification_review_schedule crs ON di.id = crs.data_inventory_id
    WHERE crs.next_review_date < CURRENT_DATE
    AND crs.status = 'pending'
    ORDER BY di.last_reviewed ASC;
END;
$$;

COMMIT;