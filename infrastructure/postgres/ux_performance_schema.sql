-- =============================================================================
-- UX & PERFORMANCE SCHEMA
-- Time-to-complete tracking and progressive trust configuration
-- =============================================================================

-- Risk level enumeration
CREATE TYPE risk_level AS ENUM (
    'very_low',
    'low',
    'medium',
    'high',
    'very_high'
);

-- =============================================================================
-- PERFORMANCE METRICS
-- =============================================================================

CREATE TABLE IF NOT EXISTS performance_metrics (
    id SERIAL PRIMARY KEY,
    
    -- Session identification
    session_id VARCHAR(100) NOT NULL UNIQUE,
    
    -- Timing breakdown
    session_start TIMESTAMP NOT NULL,
    consent_shown_timestamp TIMESTAMP,
    consent_granted_timestamp TIMESTAMP,
    challenge_issued_timestamp TIMESTAMP,
    video_upload_start_timestamp TIMESTAMP,
    video_upload_complete_timestamp TIMESTAMP,
    processing_start_timestamp TIMESTAMP,
    processing_complete_timestamp TIMESTAMP,
    result_returned_timestamp TIMESTAMP,
    
    -- Calculated durations (milliseconds)
    total_duration_ms INTEGER,
    consent_duration_ms INTEGER,
    upload_duration_ms INTEGER,
    processing_duration_ms INTEGER,
    
    -- User experience
    success BOOLEAN NOT NULL DEFAULT FALSE,
    abandonment BOOLEAN NOT NULL DEFAULT FALSE,
    error_occurred BOOLEAN NOT NULL DEFAULT FALSE,
    error_code VARCHAR(100),
    
    -- Progressive trust
    risk_level risk_level,
    challenge_count INTEGER,
    difficulty_level VARCHAR(20),
    
    -- Device info
    device_type VARCHAR(50),
    browser VARCHAR(50),
    
    -- Indexes
    INDEX idx_perf_session (session_id),
    INDEX idx_perf_success (success),
    INDEX idx_perf_duration (total_duration_ms),
    INDEX idx_perf_risk (risk_level),
    INDEX idx_perf_timestamp (session_start DESC)
);

COMMENT ON TABLE performance_metrics IS 'Performance tracking for time-to-complete (target: <=20s median)';

-- =============================================================================
-- PROGRESSIVE TRUST CONFIGURATION
-- =============================================================================

CREATE TABLE IF NOT EXISTS progressive_trust_config (
    id SERIAL PRIMARY KEY,
    
    -- Configuration
    risk_level risk_level NOT NULL UNIQUE,
    
    -- Challenge requirements
    challenge_count INTEGER NOT NULL,
    challenge_types TEXT[] NOT NULL,
    difficulty_level VARCHAR(20) NOT NULL,
    
    -- Time targets
    target_duration_seconds INTEGER NOT NULL,
    
    -- UI optimizations
    skip_intro BOOLEAN NOT NULL DEFAULT FALSE,
    pre_cache_challenges BOOLEAN NOT NULL DEFAULT FALSE,
    enable_fast_path BOOLEAN NOT NULL DEFAULT FALSE,
    
    -- Metadata
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE progressive_trust_config IS 'Progressive trust profiles for risk-based friction';

-- Insert default configurations
INSERT INTO progressive_trust_config (
    risk_level, challenge_count, challenge_types, difficulty_level,
    target_duration_seconds, skip_intro, pre_cache_challenges, enable_fast_path
) VALUES
    ('very_low', 1, ARRAY['blink'], 'easy', 10, TRUE, TRUE, TRUE),
    ('low', 1, ARRAY['head_turn_left', 'blink'], 'easy', 15, TRUE, TRUE, TRUE),
    ('medium', 2, ARRAY['head_turn_left', 'blink', 'smile'], 'medium', 20, FALSE, TRUE, FALSE),
    ('high', 3, ARRAY['head_turn_left', 'head_turn_right', 'blink', 'smile'], 'medium', 30, FALSE, FALSE, FALSE),
    ('very_high', 4, ARRAY['head_turn_left', 'head_turn_right', 'blink', 'smile', 'nod', 'raise_eyebrows'], 'hard', 45, FALSE, FALSE, FALSE)
ON CONFLICT (risk_level) DO NOTHING;

-- =============================================================================
-- ACCESSIBILITY PREFERENCES
-- =============================================================================

CREATE TABLE IF NOT EXISTS accessibility_preferences (
    id SERIAL PRIMARY KEY,
    
    -- User identification
    user_identifier VARCHAR(255),
    session_id VARCHAR(100),
    
    -- Preferences
    screen_reader_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    keyboard_only BOOLEAN NOT NULL DEFAULT FALSE,
    high_contrast BOOLEAN NOT NULL DEFAULT FALSE,
    reduced_motion BOOLEAN NOT NULL DEFAULT FALSE,
    font_size VARCHAR(20) NOT NULL DEFAULT 'normal',
    language VARCHAR(10) NOT NULL DEFAULT 'en',
    
    -- Device capabilities
    camera_available BOOLEAN NOT NULL DEFAULT TRUE,
    microphone_available BOOLEAN NOT NULL DEFAULT TRUE,
    
    -- Fallback
    needs_fallback BOOLEAN NOT NULL DEFAULT FALSE,
    fallback_reason VARCHAR(100),
    fallback_method_selected VARCHAR(50),
    
    -- Timestamps
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    
    -- Indexes
    INDEX idx_access_user (user_identifier),
    INDEX idx_access_session (session_id),
    INDEX idx_access_fallback (needs_fallback)
);

COMMENT ON TABLE accessibility_preferences IS 'User accessibility preferences and capabilities';

-- =============================================================================
-- GUIDANCE EVENTS
-- =============================================================================

CREATE TABLE IF NOT EXISTS guidance_events (
    id BIGSERIAL PRIMARY KEY,
    
    -- Session identification
    session_id VARCHAR(100) NOT NULL,
    
    -- Guidance details
    phase VARCHAR(50) NOT NULL,
    message_key VARCHAR(100) NOT NULL,
    message_text TEXT,
    language VARCHAR(10) NOT NULL,
    
    -- User interaction
    shown_at TIMESTAMP NOT NULL DEFAULT NOW(),
    acknowledged BOOLEAN NOT NULL DEFAULT FALSE,
    acknowledged_at TIMESTAMP,
    
    -- Effectiveness
    helpful_rating INTEGER CHECK (helpful_rating BETWEEN 1 AND 5),
    
    -- Indexes
    INDEX idx_guidance_session (session_id),
    INDEX idx_guidance_phase (phase),
    INDEX idx_guidance_shown (shown_at DESC)
);

COMMENT ON TABLE guidance_events IS 'Real-time guidance event tracking';

-- =============================================================================
-- HELPER FUNCTIONS
-- =============================================================================

-- Function to calculate performance statistics
CREATE OR REPLACE FUNCTION get_performance_stats(
    p_time_window_hours INTEGER DEFAULT 24
)
RETURNS TABLE (
    total_sessions BIGINT,
    median_ms NUMERIC,
    mean_ms NUMERIC,
    p95_ms NUMERIC,
    target_met BOOLEAN
)
LANGUAGE plpgsql
AS $$
DECLARE
    v_cutoff TIMESTAMP;
    v_median NUMERIC;
    v_target_ms INTEGER := 20000; -- 20 seconds
BEGIN
    v_cutoff := NOW() - INTERVAL '1 hour' * p_time_window_hours;
    
    -- Get median
    SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY total_duration_ms)
    INTO v_median
    FROM performance_metrics
    WHERE session_start >= v_cutoff
    AND success = TRUE
    AND total_duration_ms IS NOT NULL;
    
    RETURN QUERY
    SELECT
        COUNT(*)::BIGINT as total_sessions,
        v_median as median_ms,
        AVG(total_duration_ms)::NUMERIC as mean_ms,
        PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY total_duration_ms)::NUMERIC as p95_ms,
        (v_median <= v_target_ms) as target_met
    FROM performance_metrics
    WHERE session_start >= v_cutoff
    AND success = TRUE
    AND total_duration_ms IS NOT NULL;
END;
$$;

-- Function to determine risk level
CREATE OR REPLACE FUNCTION determine_risk_level(
    p_user_identifier VARCHAR,
    p_device_id VARCHAR,
    p_transaction_value NUMERIC DEFAULT NULL,
    p_action_type VARCHAR DEFAULT 'login'
)
RETURNS risk_level
LANGUAGE plpgsql
AS $$
DECLARE
    v_risk_score NUMERIC := 0.0;
    v_success_count INTEGER;
    v_device_count INTEGER;
    v_risk_level risk_level;
BEGIN
    -- Check user history
    IF p_user_identifier IS NOT NULL THEN
        SELECT COUNT(*)
        INTO v_success_count
        FROM verification_results vr
        JOIN sessions s ON vr.session_id = s.session_id
        WHERE s.user_identifier = p_user_identifier
        AND vr.decision = 'approve'
        AND vr.created_at >= NOW() - INTERVAL '30 days';
        
        -- More history = lower risk
        IF v_success_count >= 10 THEN
            v_risk_score := v_risk_score - 0.3;
        ELSIF v_success_count >= 5 THEN
            v_risk_score := v_risk_score - 0.2;
        ELSIF v_success_count >= 1 THEN
            v_risk_score := v_risk_score - 0.1;
        END IF;
    END IF;
    
    -- Check device trust
    SELECT COUNT(*)
    INTO v_device_count
    FROM sessions
    WHERE device_id = p_device_id
    AND created_at >= NOW() - INTERVAL '30 days';
    
    IF v_device_count >= 5 THEN
        v_risk_score := v_risk_score - 0.2;
    ELSIF v_device_count >= 2 THEN
        v_risk_score := v_risk_score - 0.1;
    END IF;
    
    -- Transaction value
    IF p_transaction_value IS NOT NULL THEN
        IF p_transaction_value > 10000 THEN
            v_risk_score := v_risk_score + 0.4;
        ELSIF p_transaction_value > 1000 THEN
            v_risk_score := v_risk_score + 0.2;
        ELSIF p_transaction_value > 100 THEN
            v_risk_score := v_risk_score + 0.1;
        END IF;
    END IF;
    
    -- Action type
    IF p_action_type IN ('payment', 'withdrawal', 'account_deletion') THEN
        v_risk_score := v_risk_score + 0.3;
    END IF;
    
    -- Map to risk level
    IF v_risk_score <= -0.3 THEN
        v_risk_level := 'very_low';
    ELSIF v_risk_score <= 0 THEN
        v_risk_level := 'low';
    ELSIF v_risk_score <= 0.3 THEN
        v_risk_level := 'medium';
    ELSIF v_risk_score <= 0.6 THEN
        v_risk_level := 'high';
    ELSE
        v_risk_level := 'very_high';
    END IF;
    
    RETURN v_risk_level;
END;
$$;

COMMIT;