"""
Purpose Limitation Enforcement
GDPR Article 5(1)(b) - Data collected for specified, explicit, and legitimate purposes
"""

from typing import Dict, Any, List, Optional
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class DataPurpose(str, Enum):
    """Allowed data processing purposes"""
    IDENTITY_VERIFICATION = "identity_verification"
    FRAUD_PREVENTION = "fraud_prevention"
    COMPLIANCE = "compliance"
    SERVICE_IMPROVEMENT = "service_improvement"
    SECURITY = "security"


class DataMinimizationProfile:
    """
    Data Minimization Profiles
    
    Defines EXACTLY what data can be collected/processed for each purpose
    GDPR Article 5(1)(c) - Data minimization
    """
    
    # What data is allowed for each purpose
    ALLOWED_DATA_BY_PURPOSE = {
        DataPurpose.IDENTITY_VERIFICATION: {
            "tables": ["sessions", "challenges", "verification_results"],
            "fields": {
                "sessions": ["session_id", "device_id", "created_at"],
                "challenges": ["challenge_id", "challenge_type", "created_at"],
                "verification_results": [
                    "verification_id",
                    "liveness_score",
                    "motion_score",
                    "temporal_score",
                    "decision",
                    "created_at"
                ]
            },
            "sensitive_fields": ["liveness_score", "motion_score", "temporal_score"],
            "retention_days": 90
        },
        
        DataPurpose.FRAUD_PREVENTION: {
            "tables": [
                "sessions",
                "verification_results",
                "risk_assessments",
                "video_uploads"
            ],
            "fields": {
                "sessions": ["session_id", "device_id", "ip_address", "user_agent", "created_at"],
                "verification_results": [
                    "verification_id",
                    "liveness_score",
                    "motion_score",
                    "temporal_score",
                    "anti_spoof_score",
                    "decision",
                    "created_at"
                ],
                "risk_assessments": [
                    "assessment_id",
                    "overall_risk_score",
                    "risk_factors",
                    "created_at"
                ],
                "video_uploads": ["upload_id", "file_size_bytes", "content_hash", "uploaded_at"]
            },
            "sensitive_fields": [
                "liveness_score",
                "motion_score",
                "temporal_score",
                "anti_spoof_score",
                "overall_risk_score",
                "risk_factors"
            ],
            "retention_days": 90
        },
        
        DataPurpose.COMPLIANCE: {
            "tables": ["explainability_records"],
            "fields": {
                "explainability_records": [
                    "record_id",
                    "session_id",
                    "decision",
                    "summary_explanation",
                    "created_at"
                ]
            },
            "sensitive_fields": [],
            "retention_days": 2555  # 7 years
        },
        
        DataPurpose.SERVICE_IMPROVEMENT: {
            "tables": ["api_requests"],
            "fields": {
                "api_requests": [
                    "endpoint",
                    "status_code",
                    "duration_ms",
                    "timestamp"
                ]
            },
            "sensitive_fields": [],
            "retention_days": 30
        },
        
        DataPurpose.SECURITY: {
            "tables": ["sessions", "verification_results"],
            "fields": {
                "sessions": ["session_id", "ip_address", "created_at"],
                "verification_results": ["verification_id", "decision", "created_at"]
            },
            "sensitive_fields": [],
            "retention_days": 90
        }
    }


class PurposeLimitationEnforcer:
    """
    Purpose Limitation Enforcer
    
    Ensures data is only used for stated purposes
    
    Features:
    - Validates data access against purpose
    - Enforces data minimization
    - Logs purpose violations
    - Automatic data filtering
    """
    
    def __init__(self):
        self.violation_log = []
    
    def validate_data_access(
        self,
        purpose: DataPurpose,
        table_name: str,
        fields_requested: List[str]
    ) -> Dict[str, Any]:
        """
        Validate that data access is allowed for stated purpose
        
        Args:
            purpose: Stated purpose for data access
            table_name: Table being accessed
            fields_requested: Fields being requested
        
        Returns:
            Validation result with allowed fields
        """
        
        profile = DataMinimizationProfile.ALLOWED_DATA_BY_PURPOSE.get(purpose)
        
        if not profile:
            self._log_violation(
                purpose=purpose.value,
                table_name=table_name,
                reason="Invalid purpose"
            )
            return {
                "allowed": False,
                "reason": "Invalid purpose",
                "allowed_fields": []
            }
        
        # Check if table is allowed for this purpose
        if table_name not in profile["tables"]:
            self._log_violation(
                purpose=purpose.value,
                table_name=table_name,
                reason=f"Table not allowed for purpose {purpose.value}"
            )
            return {
                "allowed": False,
                "reason": f"Table {table_name} not allowed for purpose {purpose.value}",
                "allowed_fields": []
            }
        
        # Get allowed fields for this table/purpose
        allowed_fields = profile["fields"].get(table_name, [])
        
        # Check which requested fields are allowed
        disallowed_fields = [f for f in fields_requested if f not in allowed_fields]
        
        if disallowed_fields:
            self._log_violation(
                purpose=purpose.value,
                table_name=table_name,
                reason=f"Fields not allowed: {', '.join(disallowed_fields)}"
            )
            
            logger.warning(
                f"⚠️  Purpose limitation violation:\n"
                f"   Purpose: {purpose.value}\n"
                f"   Table: {table_name}\n"
                f"   Disallowed fields: {', '.join(disallowed_fields)}\n"
                f"   Allowed fields: {', '.join(allowed_fields)}"
            )
            
            return {
                "allowed": False,
                "reason": f"Fields not allowed: {', '.join(disallowed_fields)}",
                "allowed_fields": allowed_fields,
                "disallowed_fields": disallowed_fields
            }
        
        logger.info(
            f"✅ Purpose limitation check passed:\n"
            f"   Purpose: {purpose.value}\n"
            f"   Table: {table_name}\n"
            f"   Fields: {', '.join(fields_requested)}"
        )
        
        return {
            "allowed": True,
            "allowed_fields": fields_requested,
            "sensitive_fields": [
                f for f in fields_requested
                if f in profile["sensitive_fields"]
            ]
        }
    
    def filter_data_by_purpose(
        self,
        purpose: DataPurpose,
        table_name: str,
        data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Filter data to only include fields allowed for purpose
        
        Args:
            purpose: Stated purpose
            table_name: Table name
            data: Raw data dictionary
        
        Returns:
            Filtered data dictionary
        """
        
        profile = DataMinimizationProfile.ALLOWED_DATA_BY_PURPOSE.get(purpose)
        
        if not profile or table_name not in profile["tables"]:
            logger.error(
                f"❌ Cannot filter data: Invalid purpose/table combination\n"
                f"   Purpose: {purpose.value}\n"
                f"   Table: {table_name}"
            )
            return {}
        
        allowed_fields = profile["fields"].get(table_name, [])
        
        # Filter data to only allowed fields
        filtered_data = {
            field: value
            for field, value in data.items()
            if field in allowed_fields
        }
        
        removed_fields = set(data.keys()) - set(filtered_data.keys())
        
        if removed_fields:
            logger.info(
                f"🔒 Data filtered by purpose limitation:\n"
                f"   Purpose: {purpose.value}\n"
                f"   Table: {table_name}\n"
                f"   Removed fields: {', '.join(removed_fields)}"
            )
        
        return filtered_data
    
    def get_retention_period(self, purpose: DataPurpose) -> int:
        """
        Get retention period for purpose
        
        Args:
            purpose: Data purpose
        
        Returns:
            Retention period in days
        """
        
        profile = DataMinimizationProfile.ALLOWED_DATA_BY_PURPOSE.get(purpose)
        return profile["retention_days"] if profile else 90
    
    def _log_violation(self, purpose: str, table_name: str, reason: str):
        """Log purpose limitation violation"""
        
        violation = {
            "timestamp": str(datetime.utcnow()),
            "purpose": purpose,
            "table_name": table_name,
            "reason": reason
        }
        
        self.violation_log.append(violation)
        
        logger.error(
            f"❌ Purpose limitation VIOLATION:\n"
            f"   Purpose: {purpose}\n"
            f"   Table: {table_name}\n"
            f"   Reason: {reason}"
        )
    
    def get_violation_report(self) -> List[Dict[str, Any]]:
        """Get all purpose limitation violations"""
        return self.violation_log.copy()


# Global instance
purpose_enforcer = PurposeLimitationEnforcer()