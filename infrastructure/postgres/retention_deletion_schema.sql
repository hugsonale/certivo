-- =============================================================================
-- RETENTION AND DELETION SCHEMA
-- Supports configurable retention, automatic deletion, and erasure workflows
-- =============================================================================

-- Jurisdiction enumeration
CREATE TYPE jurisdiction_type AS ENUM (
    'eu',
    'us_ca',
    'us_other',
    'uk',
    'canada',
    'australia',
    'japan',
    'global'
);

-- Deletion type enumeration
CREATE TYPE deletion_type AS ENUM (
    'automatic',
    'user_request',
    'tenant_request',
    'admin_manual'
);

-- Deletion status enumeration
CREATE TYPE deletion_status AS ENUM (
    'pending',
    'in_progress',
    'completed',
    'failed',
    'cancelled'
);

-- =============================================================================
-- RETENTION POLICIES
-- =============================================================================

CREATE TABLE IF NOT EXISTS retention_policies (
    id SERIAL PRIMARY KEY,
    
    -- Policy identification
    table_name VARCHAR(100) NOT NULL,
    jurisdiction jurisdiction_type NOT NULL,
    tenant_id VARCHAR(100),  -- NULL for global policy
    
    -- Retention configuration
    retention_days INTEGER NOT NULL DEFAULT 90,
    grace_period_days INTEGER NOT NULL DEFAULT 30,
    
    -- Custom policy
    custom_retention BOOLEAN NOT NULL DEFAULT FALSE,
    retention_reason TEXT,
    
    -- Legal hold
    legal_hold BOOLEAN NOT NULL DEFAULT FALSE,
    legal_hold_reason TEXT,
    
    -- Audit
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    created_by VARCHAR(255),
    
    -- Constraints
    UNIQUE(table_name, jurisdiction, COALESCE(tenant_id, '')),
    
    -- Indexes
    INDEX idx_retention_table (table_name),
    INDEX idx_retention_jurisdiction (jurisdiction),
    INDEX idx_retention_tenant (tenant_id),
    INDEX idx_retention_legal_hold (legal_hold)
);

COMMENT ON TABLE retention_policies IS 'Configurable retention windows by tenant/jurisdiction';

-- =============================================================================
-- DELETION JOBS
-- =============================================================================

CREATE TABLE IF NOT EXISTS deletion_jobs (
    id SERIAL PRIMARY KEY,
    
    -- Job identification
    job_id VARCHAR(100) NOT NULL UNIQUE,
    deletion_type deletion_type NOT NULL,
    
    -- Target
    table_name VARCHAR(100) NOT NULL,
    tenant_id VARCHAR(100),
    user_identifier VARCHAR(255),
    
    -- Execution
    status deletion_status NOT NULL DEFAULT 'pending',
    records_identified INTEGER NOT NULL DEFAULT 0,
    records_deleted INTEGER NOT NULL DEFAULT 0,
    records_failed INTEGER NOT NULL DEFAULT 0,
    
    -- Audit
    initiated_by VARCHAR(255) NOT NULL DEFAULT 'system',
    initiated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    
    -- Verification
    verification_token VARCHAR(100),
    verification_completed BOOLEAN NOT NULL DEFAULT FALSE,
    
    -- Error tracking
    error_message TEXT,
    
    -- Indexes
    INDEX idx_deletion_job_id (job_id),
    INDEX idx_deletion_status (status),
    INDEX idx_deletion_table (table_name),
    INDEX idx_deletion_initiated (initiated_at DESC)
);

COMMENT ON TABLE deletion_jobs IS 'Automatic deletion jobs with audit trail';

-- =============================================================================
-- DELETION AUDIT LOG
-- =============================================================================

CREATE TABLE IF NOT EXISTS deletion_audit_log (
    id BIGSERIAL PRIMARY KEY,
    
    -- Deletion details
    job_id VARCHAR(100),
    table_name VARCHAR(100) NOT NULL,
    record_id VARCHAR(255) NOT NULL,
    record_data JSONB,
    
    -- Deletion metadata
    deletion_type deletion_type,
    deletion_reason TEXT,
    
    -- Audit
    deleted_at TIMESTAMP NOT NULL DEFAULT NOW(),
    deleted_by VARCHAR(255) NOT NULL DEFAULT 'system',
    
    -- Indexes
    INDEX idx_deletion_audit_job (job_id),
    INDEX idx_deletion_audit_table (table_name),
    INDEX idx_deletion_audit_deleted (deleted_at DESC)
) PARTITION BY RANGE (deleted_at);

COMMENT ON TABLE deletion_audit_log IS 'Audit trail for all deletions';

-- Create partitions for deletion audit log (monthly)
CREATE TABLE IF NOT EXISTS deletion_audit_log_2025_05 PARTITION OF deletion_audit_log
FOR VALUES FROM ('2025-05-01') TO ('2025-06-01');

CREATE TABLE IF NOT EXISTS deletion_audit_log_2025_06 PARTITION OF deletion_audit_log
FOR VALUES FROM ('2025-06-01') TO ('2025-07-01');

CREATE TABLE IF NOT EXISTS deletion_audit_log_2025_07 PARTITION OF deletion_audit_log
FOR VALUES FROM ('2025-07-01') TO ('2025-08-01');

-- =============================================================================
-- DATA SUBJECT REQUESTS (GDPR/CCPA)
-- =============================================================================

CREATE TABLE IF NOT EXISTS data_subject_requests (
    id SERIAL PRIMARY KEY,
    
    -- Request identification
    request_id VARCHAR(100) NOT NULL UNIQUE,
    request_type VARCHAR(50) NOT NULL,  -- access, deletion, portability, correction
    
    -- Subject identification (hashed for privacy)
    subject_identifier_hash VARCHAR(64) NOT NULL,
    
    -- Status
    status VARCHAR(50) NOT NULL DEFAULT 'pending',
    
    -- Timeline (30-day SLA)
    requested_at TIMESTAMP NOT NULL,
    acknowledged_at TIMESTAMP,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    deadline TIMESTAMP NOT NULL,
    
    -- Processing details
    tables_accessed TEXT[],
    records_found INTEGER,
    
    -- Actions taken
    data_exported BOOLEAN NOT NULL DEFAULT FALSE,
    data_deleted BOOLEAN NOT NULL DEFAULT FALSE,
    data_corrected BOOLEAN NOT NULL DEFAULT FALSE,
    
    -- Request metadata
    request_source VARCHAR(100),  -- email, web_form, api
    notes TEXT,
    
    -- Assignment
    assigned_to VARCHAR(255),
    
    -- Audit
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    
    -- Indexes
    INDEX idx_dsr_request_id (request_id),
    INDEX idx_dsr_status (status),
    INDEX idx_dsr_deadline (deadline),
    INDEX idx_dsr_type (request_type),
    INDEX idx_dsr_requested (requested_at DESC)
);

COMMENT ON TABLE data_subject_requests IS 'GDPR/CCPA data subject access and erasure requests';

-- =============================================================================
-- HELPER FUNCTIONS
-- =============================================================================

-- Function to get records ready for deletion
CREATE OR REPLACE FUNCTION get_records_for_deletion(
    p_table_name VARCHAR,
    p_retention_days INTEGER
)
RETURNS TABLE (
    record_count BIGINT
)
LANGUAGE plpgsql
AS $$
DECLARE
    v_cutoff_date TIMESTAMP;
BEGIN
    v_cutoff_date := NOW() - INTERVAL '1 day' * p_retention_days;
    
    RETURN QUERY EXECUTE format(
        'SELECT COUNT(*) FROM %I WHERE created_at < $1 AND deleted_at IS NULL',
        p_table_name
    ) USING v_cutoff_date;
END;
$$;

-- Function to check SLA compliance
CREATE OR REPLACE FUNCTION check_deletion_sla()
RETURNS TABLE (
    request_id VARCHAR,
    days_remaining INTEGER,
    status VARCHAR,
    overdue BOOLEAN
)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    SELECT 
        dsr.request_id,
        EXTRACT(DAY FROM dsr.deadline - NOW())::INTEGER as days_remaining,
        dsr.status,
        (dsr.deadline < NOW() AND dsr.status != 'completed') as overdue
    FROM data_subject_requests dsr
    WHERE dsr.request_type = 'deletion'
    AND dsr.status IN ('pending', 'acknowledged', 'in_progress')
    ORDER BY dsr.deadline ASC;
END;
$$;

-- Function to log deletion
CREATE OR REPLACE FUNCTION log_deletion(
    p_job_id VARCHAR,
    p_table_name VARCHAR,
    p_record_id VARCHAR,
    p_record_data JSONB,
    p_deletion_type deletion_type
)
RETURNS VOID
LANGUAGE plpgsql
AS $$
BEGIN
    INSERT INTO deletion_audit_log (
        job_id,
        table_name,
        record_id,
        record_data,
        deletion_type
    ) VALUES (
        p_job_id,
        p_table_name,
        p_record_id,
        p_record_data,
        p_deletion_type
    );
END;
$$;

COMMIT;