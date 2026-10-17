"""
Certivo Data Classifications
Complete classification of all data fields in the Certivo system
"""

from services.shared.data_classification import (
    DataClassification,
    RetentionPolicy,
    FieldClassification,
    DataInventoryEntry,
    registry
)


def initialize_certivo_data_classifications():
    """
    Initialize all Certivo data classifications
    
    This is the master data inventory for Certivo
    """
    
    # =========================================================================
    # TABLE: sessions
    # Purpose: Track user verification sessions
    # =========================================================================
    
    sessions_fields = [
        FieldClassification(
            field_name="session_id",
            table_name="sessions",
            classification=DataClassification.INTERNAL,
            description="Unique session identifier",
            data_type="VARCHAR(100)",
            owner="platform-team@certivo.com",
            business_unit="Engineering",
            retention_policy=RetentionPolicy.MEDIUM_TERM,
            retention_days=90,
            pii=False,
            encryption_required=False,
            purpose="Session tracking and correlation"
        ),
        FieldClassification(
            field_name="device_id",
            table_name="sessions",
            classification=DataClassification.SENSITIVE,
            description="Device fingerprint identifier",
            data_type="VARCHAR(100)",
            owner="platform-team@certivo.com",
            business_unit="Engineering",
            retention_policy=RetentionPolicy.MEDIUM_TERM,
            retention_days=90,
            pii=True,
            gdpr_applicable=True,
            ccpa_applicable=True,
            encryption_required=True,
            encryption_at_rest=True,
            access_logging_required=True,
            purpose="Device identification for fraud detection",
            legal_basis="Legitimate interest - fraud prevention"
        ),
        FieldClassification(
            field_name="ip_address",
            table_name="sessions",
            classification=DataClassification.SENSITIVE,
            description="User IP address",
            data_type="INET",
            owner="platform-team@certivo.com",
            business_unit="Engineering",
            retention_policy=RetentionPolicy.MEDIUM_TERM,
            retention_days=90,
            pii=True,
            gdpr_applicable=True,
            ccpa_applicable=True,
            encryption_required=True,
            encryption_at_rest=True,
            access_logging_required=True,
            purpose="Geolocation and fraud detection",
            legal_basis="Legitimate interest - fraud prevention"
        ),
        FieldClassification(
            field_name="user_agent",
            table_name="sessions",
            classification=DataClassification.INTERNAL,
            description="Browser user agent string",
            data_type="TEXT",
            owner="platform-team@certivo.com",
            business_unit="Engineering",
            retention_policy=RetentionPolicy.MEDIUM_TERM,
            retention_days=90,
            pii=False,
            purpose="Browser compatibility and fraud detection"
        ),
        FieldClassification(
            field_name="created_at",
            table_name="sessions",
            classification=DataClassification.INTERNAL,
            description="Session creation timestamp",
            data_type="TIMESTAMP",
            owner="platform-team@certivo.com",
            business_unit="Engineering",
            retention_policy=RetentionPolicy.MEDIUM_TERM,
            retention_days=90,
            pii=False,
            purpose="Session lifecycle tracking"
        ),
    ]
    
    registry.register_table(DataInventoryEntry(
        table_name="sessions",
        database_name="certivo",
        schema_name="public",
        fields=sessions_fields,
        data_owner="platform-team@certivo.com",
        technical_owner="sre-team@certivo.com",
        business_unit="Engineering",
        purpose="Track user verification sessions for fraud detection and analytics",
        legal_basis="Legitimate interest - service provision and fraud prevention",
        encryption_enabled=True,
        access_controls=["role:platform_engineer", "role:data_analyst"],
        contains_pii=True,
        contains_phi=False,
        gdpr_applicable=True,
        ccpa_applicable=True,
        default_retention_policy=RetentionPolicy.MEDIUM_TERM,
        retention_days=90
    ))
    
    # =========================================================================
    # TABLE: challenges
    # Purpose: Store challenge data
    # =========================================================================
    
    challenges_fields = [
        FieldClassification(
            field_name="challenge_id",
            table_name="challenges",
            classification=DataClassification.INTERNAL,
            description="Unique challenge identifier",
            data_type="VARCHAR(100)",
            owner="platform-team@certivo.com",
            business_unit="Engineering",
            retention_policy=RetentionPolicy.SHORT_TERM,
            retention_days=7,
            pii=False,
            purpose="Challenge tracking"
        ),
        FieldClassification(
            field_name="session_id",
            table_name="challenges",
            classification=DataClassification.INTERNAL,
            description="Associated session identifier",
            data_type="VARCHAR(100)",
            owner="platform-team@certivo.com",
            business_unit="Engineering",
            retention_policy=RetentionPolicy.SHORT_TERM,
            retention_days=7,
            pii=False,
            purpose="Link challenge to session"
        ),
        FieldClassification(
            field_name="challenge_type",
            table_name="challenges",
            classification=DataClassification.PUBLIC,
            description="Type of challenge (head_turn, blink, etc.)",
            data_type="VARCHAR(50)",
            owner="platform-team@certivo.com",
            business_unit="Engineering",
            retention_policy=RetentionPolicy.SHORT_TERM,
            retention_days=7,
            pii=False,
            purpose="Challenge analytics"
        ),
        FieldClassification(
            field_name="challenge_data",
            table_name="challenges",
            classification=DataClassification.INTERNAL,
            description="Challenge parameters and metadata",
            data_type="JSONB",
            owner="platform-team@certivo.com",
            business_unit="Engineering",
            retention_policy=RetentionPolicy.SHORT_TERM,
            retention_days=7,
            pii=False,
            purpose="Challenge configuration"
        ),
        FieldClassification(
            field_name="created_at",
            table_name="challenges",
            classification=DataClassification.INTERNAL,
            description="Challenge creation timestamp",
            data_type="TIMESTAMP",
            owner="platform-team@certivo.com",
            business_unit="Engineering",
            retention_policy=RetentionPolicy.SHORT_TERM,
            retention_days=7,
            pii=False,
            purpose="Challenge lifecycle tracking"
        ),
    ]
    
    registry.register_table(DataInventoryEntry(
        table_name="challenges",
        database_name="certivo",
        schema_name="public",
        fields=challenges_fields,
        data_owner="platform-team@certivo.com",
        technical_owner="sre-team@certivo.com",
        business_unit="Engineering",
        purpose="Store challenge configuration for verification process",
        legal_basis="Legitimate interest - service provision",
        encryption_enabled=False,
        access_controls=["role:platform_engineer"],
        contains_pii=False,
        contains_phi=False,
        gdpr_applicable=False,
        ccpa_applicable=False,
        default_retention_policy=RetentionPolicy.SHORT_TERM,
        retention_days=7
    ))
    
    # =========================================================================
    # TABLE: verification_results
    # Purpose: Store verification outcomes
    # =========================================================================
    
    verification_results_fields = [
        FieldClassification(
            field_name="verification_id",
            table_name="verification_results",
            classification=DataClassification.INTERNAL,
            description="Unique verification result identifier",
            data_type="VARCHAR(100)",
            owner="platform-team@certivo.com",
            business_unit="Engineering",
            retention_policy=RetentionPolicy.MEDIUM_TERM,
            retention_days=90,
            pii=False,
            purpose="Result tracking"
        ),
        FieldClassification(
            field_name="session_id",
            table_name="verification_results",
            classification=DataClassification.INTERNAL,
            description="Associated session identifier",
            data_type="VARCHAR(100)",
            owner="platform-team@certivo.com",
            business_unit="Engineering",
            retention_policy=RetentionPolicy.MEDIUM_TERM,
            retention_days=90,
            pii=False,
            purpose="Link result to session"
        ),
        FieldClassification(
            field_name="liveness_score",
            table_name="verification_results",
            classification=DataClassification.BIOMETRIC_ADJACENT,
            description="Liveness detection score (0-1)",
            data_type="DECIMAL(5,4)",
            owner="ml-team@certivo.com",
            business_unit="Machine Learning",
            retention_policy=RetentionPolicy.MEDIUM_TERM,
            retention_days=90,
            pii=False,
            gdpr_applicable=True,
            ccpa_applicable=True,
            encryption_required=True,
            encryption_at_rest=True,
            access_logging_required=True,
            purpose="Liveness verification - derived from facial movements",
            legal_basis="Legitimate interest - service provision and fraud prevention"
        ),
        FieldClassification(
            field_name="motion_score",
            table_name="verification_results",
            classification=DataClassification.BIOMETRIC_ADJACENT,
            description="Motion analysis score",
            data_type="DECIMAL(5,4)",
            owner="ml-team@certivo.com",
            business_unit="Machine Learning",
            retention_policy=RetentionPolicy.MEDIUM_TERM,
            retention_days=90,
            pii=False,
            gdpr_applicable=True,
            ccpa_applicable=True,
            encryption_required=True,
            encryption_at_rest=True,
            access_logging_required=True,
            purpose="Motion pattern analysis - derived from facial movements",
            legal_basis="Legitimate interest - fraud prevention"
        ),
        FieldClassification(
            field_name="temporal_score",
            table_name="verification_results",
            classification=DataClassification.BIOMETRIC_ADJACENT,
            description="Temporal consistency score",
            data_type="DECIMAL(5,4)",
            owner="ml-team@certivo.com",
            business_unit="Machine Learning",
            retention_policy=RetentionPolicy.MEDIUM_TERM,
            retention_days=90,
            pii=False,
            gdpr_applicable=True,
            ccpa_applicable=True,
            encryption_required=True,
            encryption_at_rest=True,
            access_logging_required=True,
            purpose="Temporal analysis - derived from facial landmarks over time",
            legal_basis="Legitimate interest - fraud prevention"
        ),
        FieldClassification(
            field_name="decision",
            table_name="verification_results",
            classification=DataClassification.SENSITIVE,
            description="Verification decision (approve/deny/review)",
            data_type="VARCHAR(20)",
            owner="platform-team@certivo.com",
            business_unit="Engineering",
            retention_policy=RetentionPolicy.MEDIUM_TERM,
            retention_days=90,
            pii=False,
            encryption_required=True,
            access_logging_required=True,
            purpose="Verification outcome for audit trail"
        ),
        FieldClassification(
            field_name="created_at",
            table_name="verification_results",
            classification=DataClassification.INTERNAL,
            description="Result creation timestamp",
            data_type="TIMESTAMP",
            owner="platform-team@certivo.com",
            business_unit="Engineering",
            retention_policy=RetentionPolicy.MEDIUM_TERM,
            retention_days=90,
            pii=False,
            purpose="Result lifecycle tracking"
        ),
    ]
    
    registry.register_table(DataInventoryEntry(
        table_name="verification_results",
        database_name="certivo",
        schema_name="public",
        fields=verification_results_fields,
        data_owner="platform-team@certivo.com",
        technical_owner="sre-team@certivo.com",
        business_unit="Engineering",
        purpose="Store verification outcomes for audit and compliance",
        legal_basis="Legitimate interest - service provision and fraud prevention",
        encryption_enabled=True,
        access_controls=["role:platform_engineer", "role:compliance_officer"],
        contains_pii=False,
        contains_phi=False,
        gdpr_applicable=True,
        ccpa_applicable=True,
        default_retention_policy=RetentionPolicy.MEDIUM_TERM,
        retention_days=90
    ))
    
    # =========================================================================
    # TABLE: video_uploads
    # Purpose: Track video file uploads (S3 metadata only, not video content)
    # =========================================================================
    
    video_uploads_fields = [
        FieldClassification(
            field_name="upload_id",
            table_name="video_uploads",
            classification=DataClassification.INTERNAL,
            description="Unique upload identifier",
            data_type="VARCHAR(100)",
            owner="platform-team@certivo.com",
            business_unit="Engineering",
            retention_policy=RetentionPolicy.MEDIUM_TERM,
            retention_days=90,
            pii=False,
            purpose="Upload tracking"
        ),
        FieldClassification(
            field_name="session_id",
            table_name="video_uploads",
            classification=DataClassification.INTERNAL,
            description="Associated session identifier",
            data_type="VARCHAR(100)",
            owner="platform-team@certivo.com",
            business_unit="Engineering",
            retention_policy=RetentionPolicy.MEDIUM_TERM,
            retention_days=90,
            pii=False,
            purpose="Link upload to session"
        ),
        FieldClassification(
            field_name="s3_key",
            table_name="video_uploads",
            classification=DataClassification.SENSITIVE,
            description="S3 object key for video file",
            data_type="VARCHAR(500)",
            owner="platform-team@certivo.com",
            business_unit="Engineering",
            retention_policy=RetentionPolicy.MEDIUM_TERM,
            retention_days=90,
            pii=False,
            encryption_required=True,
            encryption_at_rest=True,
            access_logging_required=True,
            purpose="Video file location reference"
        ),
        FieldClassification(
            field_name="file_size_bytes",
            table_name="video_uploads",
            classification=DataClassification.INTERNAL,
            description="Video file size in bytes",
            data_type="BIGINT",
            owner="platform-team@certivo.com",
            business_unit="Engineering",
            retention_policy=RetentionPolicy.MEDIUM_TERM,
            retention_days=90,
            pii=False,
            purpose="Storage analytics"
        ),
        FieldClassification(
            field_name="content_hash",
            table_name="video_uploads",
            classification=DataClassification.INTERNAL,
            description="SHA256 hash of video content",
            data_type="VARCHAR(64)",
            owner="platform-team@certivo.com",
            business_unit="Engineering",
            retention_policy=RetentionPolicy.MEDIUM_TERM,
            retention_days=90,
            pii=False,
            purpose="Video integrity verification"
        ),
        FieldClassification(
            field_name="uploaded_at",
            table_name="video_uploads",
            classification=DataClassification.INTERNAL,
            description="Upload timestamp",
            data_type="TIMESTAMP",
            owner="platform-team@certivo.com",
            business_unit="Engineering",
            retention_policy=RetentionPolicy.MEDIUM_TERM,
            retention_days=90,
            pii=False,
            purpose="Upload lifecycle tracking"
        ),
    ]
    
    registry.register_table(DataInventoryEntry(
        table_name="video_uploads",
        database_name="certivo",
        schema_name="public",
        fields=video_uploads_fields,
        data_owner="platform-team@certivo.com",
        technical_owner="sre-team@certivo.com",
        business_unit="Engineering",
        purpose="Track video upload metadata (S3 references only)",
        legal_basis="Legitimate interest - service provision",
        encryption_enabled=True,
        access_controls=["role:platform_engineer"],
        contains_pii=False,
        contains_phi=False,
        gdpr_applicable=True,
        ccpa_applicable=True,
        default_retention_policy=RetentionPolicy.MEDIUM_TERM,
        retention_days=90
    ))
    
    # =========================================================================
    # TABLE: risk_assessments
    # Purpose: Store risk scoring results
    # =========================================================================
    
    risk_assessments_fields = [
        FieldClassification(
            field_name="assessment_id",
            table_name="risk_assessments",
            classification=DataClassification.INTERNAL,
            description="Unique assessment identifier",
            data_type="VARCHAR(100)",
            owner="security-team@certivo.com",
            business_unit="Security",
            retention_policy=RetentionPolicy.MEDIUM_TERM,
            retention_days=90,
            pii=False,
            purpose="Assessment tracking"
        ),
        FieldClassification(
            field_name="session_id",
            table_name="risk_assessments",
            classification=DataClassification.INTERNAL,
            description="Associated session identifier",
            data_type="VARCHAR(100)",
            owner="security-team@certivo.com",
            business_unit="Security",
            retention_policy=RetentionPolicy.MEDIUM_TERM,
            retention_days=90,
            pii=False,
            purpose="Link assessment to session"
        ),
        FieldClassification(
            field_name="overall_risk_score",
            table_name="risk_assessments",
            classification=DataClassification.SENSITIVE,
            description="Overall risk score (0-1)",
            data_type="DECIMAL(5,4)",
            owner="security-team@certivo.com",
            business_unit="Security",
            retention_policy=RetentionPolicy.MEDIUM_TERM,
            retention_days=90,
            pii=False,
            encryption_required=True,
            access_logging_required=True,
            purpose="Risk assessment for fraud detection"
        ),
        FieldClassification(
            field_name="risk_factors",
            table_name="risk_assessments",
            classification=DataClassification.SENSITIVE,
            description="Individual risk factor scores (JSON)",
            data_type="JSONB",
            owner="security-team@certivo.com",
            business_unit="Security",
            retention_policy=RetentionPolicy.MEDIUM_TERM,
            retention_days=90,
            pii=False,
            encryption_required=True,
            access_logging_required=True,
            purpose="Detailed risk breakdown for analysis"
        ),
        FieldClassification(
            field_name="created_at",
            table_name="risk_assessments",
            classification=DataClassification.INTERNAL,
            description="Assessment creation timestamp",
            data_type="TIMESTAMP",
            owner="security-team@certivo.com",
            business_unit="Security",
            retention_policy=RetentionPolicy.MEDIUM_TERM,
            retention_days=90,
            pii=False,
            purpose="Assessment lifecycle tracking"
        ),
    ]
    
    registry.register_table(DataInventoryEntry(
        table_name="risk_assessments",
        database_name="certivo",
        schema_name="public",
        fields=risk_assessments_fields,
        data_owner="security-team@certivo.com",
        technical_owner="sre-team@certivo.com",
        business_unit="Security",
        purpose="Store risk assessment results for fraud detection and compliance",
        legal_basis="Legitimate interest - fraud prevention",
        encryption_enabled=True,
        access_controls=["role:security_analyst", "role:compliance_officer"],
        contains_pii=False,
        contains_phi=False,
        gdpr_applicable=True,
        ccpa_applicable=True,
        default_retention_policy=RetentionPolicy.MEDIUM_TERM,
        retention_days=90
    ))
    
    # =========================================================================
    # TABLE: explainability_records
    # Purpose: Store explainability data for denied/flagged verifications
    # =========================================================================
    
    explainability_records_fields = [
        FieldClassification(
            field_name="record_id",
            table_name="explainability_records",
            classification=DataClassification.INTERNAL,
            description="Unique explainability record identifier",
            data_type="VARCHAR(100)",
            owner="compliance-team@certivo.com",
            business_unit="Compliance",
            retention_policy=RetentionPolicy.LONG_TERM,
            retention_days=2555,  # 7 years
            pii=False,
            purpose="Audit trail for compliance"
        ),
        FieldClassification(
            field_name="session_id",
            table_name="explainability_records",
            classification=DataClassification.INTERNAL,
            description="Associated session identifier",
            data_type="VARCHAR(100)",
            owner="compliance-team@certivo.com",
            business_unit="Compliance",
            retention_policy=RetentionPolicy.LONG_TERM,
            retention_days=2555,
            pii=False,
            purpose="Link explainability to session"
        ),
        FieldClassification(
            field_name="decision",
            table_name="explainability_records",
            classification=DataClassification.SENSITIVE,
            description="Verification decision",
            data_type="VARCHAR(20)",
            owner="compliance-team@certivo.com",
            business_unit="Compliance",
            retention_policy=RetentionPolicy.LONG_TERM,
            retention_days=2555,
            pii=False,
            encryption_required=True,
            access_logging_required=True,
            purpose="Decision audit trail"
        ),
        FieldClassification(
            field_name="summary_explanation",
            table_name="explainability_records",
            classification=DataClassification.INTERNAL,
            description="User-facing explanation summary",
            data_type="TEXT",
            owner="compliance-team@certivo.com",
            business_unit="Compliance",
            retention_policy=RetentionPolicy.LONG_TERM,
            retention_days=2555,
            pii=False,
            purpose="User communication"
        ),
        FieldClassification(
            field_name="detailed_explanation",
            table_name="explainability_records",
            classification=DataClassification.SENSITIVE,
            description="Detailed technical explanation",
            data_type="TEXT",
            owner="compliance-team@certivo.com",
            business_unit="Compliance",
            retention_policy=RetentionPolicy.LONG_TERM,
            retention_days=2555,
            pii=False,
            encryption_required=True,
            access_logging_required=True,
            purpose="Technical audit trail"
        ),
        FieldClassification(
            field_name="primary_concerns",
            table_name="explainability_records",
            classification=DataClassification.SENSITIVE,
            description="Primary reasons for decision",
            data_type="TEXT[]",
            owner="compliance-team@certivo.com",
            business_unit="Compliance",
            retention_policy=RetentionPolicy.LONG_TERM,
            retention_days=2555,
            pii=False,
            encryption_required=True,
            access_logging_required=True,
            purpose="Decision justification"
        ),
        FieldClassification(
            field_name="created_at",
            table_name="explainability_records",
            classification=DataClassification.INTERNAL,
            description="Record creation timestamp",
            data_type="TIMESTAMP",
            owner="compliance-team@certivo.com",
            business_unit="Compliance",
            retention_policy=RetentionPolicy.LONG_TERM,
            retention_days=2555,
            pii=False,
            purpose="Audit trail timestamp"
        ),
    ]
    
    registry.register_table(DataInventoryEntry(
        table_name="explainability_records",
        database_name="certivo",
        schema_name="public",
        fields=explainability_records_fields,
        data_owner="compliance-team@certivo.com",
        technical_owner="sre-team@certivo.com",
        business_unit="Compliance",
        purpose="Store explainability data for audit, compliance, and appeals",
        legal_basis="Legal obligation - audit trail and right to explanation",
        encryption_enabled=True,
        access_controls=["role:compliance_officer", "role:legal"],
        contains_pii=False,
        contains_phi=False,
        gdpr_applicable=True,
        ccpa_applicable=True,
        default_retention_policy=RetentionPolicy.LONG_TERM,
        retention_days=2555  # 7 years for audit compliance
    ))
    
    # =========================================================================
    # TABLE: api_requests (SLO monitoring)
    # Purpose: Track API request metrics
    # =========================================================================
    
    api_requests_fields = [
        FieldClassification(
            field_name="id",
            table_name="api_requests",
            classification=DataClassification.INTERNAL,
            description="Auto-increment ID",
            data_type="BIGSERIAL",
            owner="platform-team@certivo.com",
            business_unit="Engineering",
            retention_policy=RetentionPolicy.SHORT_TERM,
            retention_days=30,
            pii=False,
            purpose="Request tracking"
        ),
        FieldClassification(
            field_name="endpoint",
            table_name="api_requests",
            classification=DataClassification.INTERNAL,
            description="API endpoint path",
            data_type="VARCHAR(255)",
            owner="platform-team@certivo.com",
            business_unit="Engineering",
            retention_policy=RetentionPolicy.SHORT_TERM,
            retention_days=30,
            pii=False,
            purpose="Performance monitoring"
        ),
        FieldClassification(
            field_name="status_code",
            table_name="api_requests",
            classification=DataClassification.INTERNAL,
            description="HTTP status code",
            data_type="INTEGER",
            owner="platform-team@certivo.com",
            business_unit="Engineering",
            retention_policy=RetentionPolicy.SHORT_TERM,
            retention_days=30,
            pii=False,
            purpose="Performance monitoring"
        ),
        FieldClassification(
            field_name="duration_ms",
            table_name="api_requests",
            classification=DataClassification.INTERNAL,
            description="Request duration in milliseconds",
            data_type="DECIMAL(10,3)",
            owner="platform-team@certivo.com",
            business_unit="Engineering",
            retention_policy=RetentionPolicy.SHORT_TERM,
            retention_days=30,
            pii=False,
            purpose="Performance monitoring"
        ),
        FieldClassification(
            field_name="timestamp",
            table_name="api_requests",
            classification=DataClassification.INTERNAL,
            description="Request timestamp",
            data_type="TIMESTAMP",
            owner="platform-team@certivo.com",
            business_unit="Engineering",
            retention_policy=RetentionPolicy.SHORT_TERM,
            retention_days=30,
            pii=False,
            purpose="Time-series analysis"
        ),
    ]
    
    registry.register_table(DataInventoryEntry(
        table_name="api_requests",
        database_name="certivo",
        schema_name="public",
        fields=api_requests_fields,
        data_owner="platform-team@certivo.com",
        technical_owner="sre-team@certivo.com",
        business_unit="Engineering",
        purpose="Track API performance metrics for SLO monitoring",
        legal_basis="Legitimate interest - service improvement",
        encryption_enabled=False,
        access_controls=["role:sre", "role:platform_engineer"],
        contains_pii=False,
        contains_phi=False,
        gdpr_applicable=False,
        ccpa_applicable=False,
        default_retention_policy=RetentionPolicy.SHORT_TERM,
        retention_days=30
    ))
    
    print("\n" + "="*60)
    print("✅ Certivo Data Classifications Initialized")
    print("="*60)
    
    # Generate and display inventory report
    report = registry.generate_inventory_report()
    
    print(f"\n📊 Data Inventory Summary:")
    print(f"   Total Tables: {report['summary']['total_tables']}")
    print(f"   Total Fields: {report['summary']['total_fields']}")
    print(f"   PII Tables: {report['summary']['pii_tables']}")
    print(f"   Biometric-Adjacent Tables: {report['summary']['biometric_adjacent_tables']}")
    print(f"\n📋 Classification Breakdown:")
    for classification, count in report['classification_breakdown'].items():
        print(f"   {classification.upper()}: {count} tables")
    print(f"\n⏱️  Retention Breakdown:")
    for retention, count in report['retention_breakdown'].items():
        print(f"   {retention.upper()}: {count} tables")
    
    # Export inventory
    registry.export_inventory("data_inventory.json")
    
    print("\n✅ Data inventory exported to: data_inventory.json")
    print("="*60)


if __name__ == "__main__":
    initialize_certivo_data_classifications()