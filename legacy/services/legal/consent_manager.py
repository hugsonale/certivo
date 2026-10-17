"""
Consent Management System
Explicit consent capture for video/liveness processing
"""

import asyncpg
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import json
import logging

logger = logging.getLogger(__name__)


class ConsentType(str, Enum):
    """Types of consent required"""
    VIDEO_CAPTURE = "video_capture"
    LIVENESS_DETECTION = "liveness_detection"
    BIOMETRIC_PROCESSING = "biometric_processing"
    DATA_STORAGE = "data_storage"
    DATA_ANALYSIS = "data_analysis"


class ConsentStatus(str, Enum):
    """Consent status"""
    PENDING = "pending"
    GRANTED = "granted"
    DENIED = "denied"
    WITHDRAWN = "withdrawn"
    EXPIRED = "expired"


@dataclass
class ConsentRequest:
    """Consent request details"""
    consent_id: str
    session_id: str
    user_identifier: Optional[str] = None
    
    # Consent details
    consent_types: List[ConsentType] = field(default_factory=list)
    purpose: str = ""
    jurisdiction: str = "global"
    
    # Status
    status: ConsentStatus = ConsentStatus.PENDING
    
    # Legal text shown to user
    consent_text: str = ""
    consent_version: str = "1.0"
    
    # User response
    granted_at: Optional[datetime] = None
    denied_at: Optional[datetime] = None
    withdrawn_at: Optional[datetime] = None
    
    # Metadata
    requested_at: datetime = field(default_factory=datetime.utcnow)
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    
    # Expiration
    expires_at: Optional[datetime] = None


class ConsentManager:
    """
    Consent Management System
    
    Features:
    - Explicit consent capture for video/liveness
    - Purpose limitation enforcement
    - Consent versioning
    - Withdrawal support
    - Audit trail
    - GDPR Article 7 compliance
    
    Legal Requirements:
    - Freely given (GDPR Article 4(11))
    - Specific (tied to purpose)
    - Informed (clear language)
    - Unambiguous (clear affirmative action)
    - Withdrawable (as easy as granting)
    """
    
    # Consent purposes (purpose limitation - GDPR Article 5(1)(b))
    VALID_PURPOSES = {
        "identity_verification": "Verify user identity for account access",
        "fraud_prevention": "Detect and prevent fraudulent activities",
        "compliance": "Meet legal and regulatory requirements",
        "service_improvement": "Improve verification accuracy and user experience",
        "security": "Protect account security and prevent unauthorized access"
    }
    
    # Data minimization - only collect what's necessary
    REQUIRED_CONSENT_BY_PURPOSE = {
        "identity_verification": [
            ConsentType.VIDEO_CAPTURE,
            ConsentType.LIVENESS_DETECTION,
            ConsentType.DATA_STORAGE
        ],
        "fraud_prevention": [
            ConsentType.VIDEO_CAPTURE,
            ConsentType.LIVENESS_DETECTION,
            ConsentType.BIOMETRIC_PROCESSING,
            ConsentType.DATA_ANALYSIS,
            ConsentType.DATA_STORAGE
        ],
        "compliance": [
            ConsentType.DATA_STORAGE
        ],
        "service_improvement": [
            ConsentType.DATA_ANALYSIS,
            ConsentType.DATA_STORAGE
        ],
        "security": [
            ConsentType.VIDEO_CAPTURE,
            ConsentType.LIVENESS_DETECTION
        ]
    }
    
    def __init__(self, postgres_pool: asyncpg.Pool):
        self.postgres = postgres_pool
    
    async def request_consent(
        self,
        session_id: str,
        purpose: str,
        jurisdiction: str = "global",
        user_identifier: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> ConsentRequest:
        """
        Request consent from user
        
        Args:
            session_id: Session identifier
            purpose: Purpose for data processing
            jurisdiction: Legal jurisdiction
            user_identifier: Optional user identifier
            ip_address: User IP address
            user_agent: User agent string
        
        Returns:
            Consent request
        """
        
        # Validate purpose
        if purpose not in self.VALID_PURPOSES:
            raise ValueError(f"Invalid purpose: {purpose}")
        
        # Get required consent types for purpose (data minimization)
        consent_types = self.REQUIRED_CONSENT_BY_PURPOSE[purpose]
        
        import uuid
        consent_id = f"CONSENT-{uuid.uuid4().hex[:12].upper()}"
        
        # Generate consent text
        consent_text = self._generate_consent_text(
            purpose=purpose,
            consent_types=consent_types,
            jurisdiction=jurisdiction
        )
        
        consent_request = ConsentRequest(
            consent_id=consent_id,
            session_id=session_id,
            user_identifier=user_identifier,
            consent_types=consent_types,
            purpose=purpose,
            jurisdiction=jurisdiction,
            consent_text=consent_text,
            consent_version="1.0",
            ip_address=ip_address,
            user_agent=user_agent
        )
        
        # Store consent request
        async with self.postgres.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO consent_records (
                    consent_id,
                    session_id,
                    user_identifier,
                    consent_types,
                    purpose,
                    jurisdiction,
                    status,
                    consent_text,
                    consent_version,
                    requested_at,
                    ip_address,
                    user_agent
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
                """,
                consent_request.consent_id,
                consent_request.session_id,
                consent_request.user_identifier,
                [ct.value for ct in consent_request.consent_types],
                consent_request.purpose,
                consent_request.jurisdiction,
                consent_request.status.value,
                consent_request.consent_text,
                consent_request.consent_version,
                consent_request.requested_at,
                consent_request.ip_address,
                consent_request.user_agent
            )
        
        logger.info(
            f"📋 Consent requested:\n"
            f"   Consent ID: {consent_id}\n"
            f"   Session: {session_id}\n"
            f"   Purpose: {purpose}\n"
            f"   Types: {', '.join([ct.value for ct in consent_types])}\n"
            f"   Jurisdiction: {jurisdiction}"
        )
        
        return consent_request
    
    async def grant_consent(
        self,
        consent_id: str,
        user_acknowledgment: str
    ) -> ConsentRequest:
        """
        Record user granting consent
        
        Args:
            consent_id: Consent identifier
            user_acknowledgment: User's explicit acknowledgment text
        
        Returns:
            Updated consent request
        """
        
        # Get consent request
        async with self.postgres.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM consent_records WHERE consent_id = $1",
                consent_id
            )
        
        if not row:
            raise ValueError(f"Consent request {consent_id} not found")
        
        # Update consent
        granted_at = datetime.utcnow()
        
        async with self.postgres.acquire() as conn:
            await conn.execute(
                """
                UPDATE consent_records
                SET status = $2,
                    granted_at = $3,
                    user_acknowledgment = $4
                WHERE consent_id = $1
                """,
                consent_id,
                ConsentStatus.GRANTED.value,
                granted_at,
                user_acknowledgment
            )
        
        logger.info(
            f"✅ Consent granted:\n"
            f"   Consent ID: {consent_id}\n"
            f"   Granted at: {granted_at.isoformat()}"
        )
        
        # Return updated consent
        async with self.postgres.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM consent_records WHERE consent_id = $1",
                consent_id
            )
        
        return self._row_to_consent(row)
    
    async def deny_consent(
        self,
        consent_id: str,
        reason: Optional[str] = None
    ) -> ConsentRequest:
        """
        Record user denying consent
        
        Args:
            consent_id: Consent identifier
            reason: Optional reason for denial
        
        Returns:
            Updated consent request
        """
        
        denied_at = datetime.utcnow()
        
        async with self.postgres.acquire() as conn:
            await conn.execute(
                """
                UPDATE consent_records
                SET status = $2,
                    denied_at = $3,
                    denial_reason = $4
                WHERE consent_id = $1
                """,
                consent_id,
                ConsentStatus.DENIED.value,
                denied_at,
                reason
            )
        
        logger.warning(
            f"❌ Consent denied:\n"
            f"   Consent ID: {consent_id}\n"
            f"   Reason: {reason or 'Not provided'}"
        )
        
        # Return updated consent
        async with self.postgres.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM consent_records WHERE consent_id = $1",
                consent_id
            )
        
        return self._row_to_consent(row)
    
    async def withdraw_consent(
        self,
        consent_id: str,
        reason: Optional[str] = None
    ) -> ConsentRequest:
        """
        Withdraw previously granted consent (GDPR Article 7(3))
        
        Args:
            consent_id: Consent identifier
            reason: Optional reason for withdrawal
        
        Returns:
            Updated consent request
        """
        
        withdrawn_at = datetime.utcnow()
        
        async with self.postgres.acquire() as conn:
            await conn.execute(
                """
                UPDATE consent_records
                SET status = $2,
                    withdrawn_at = $3,
                    withdrawal_reason = $4
                WHERE consent_id = $1
                """,
                consent_id,
                ConsentStatus.WITHDRAWN.value,
                withdrawn_at,
                reason
            )
        
        logger.info(
            f"🔄 Consent withdrawn:\n"
            f"   Consent ID: {consent_id}\n"
            f"   Withdrawn at: {withdrawn_at.isoformat()}\n"
            f"   Reason: {reason or 'Not provided'}"
        )
        
        # Trigger data deletion if required
        # (Implementation depends on consent type)
        await self._handle_consent_withdrawal(consent_id)
        
        # Return updated consent
        async with self.postgres.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM consent_records WHERE consent_id = $1",
                consent_id
            )
        
        return self._row_to_consent(row)
    
    async def check_consent(
        self,
        session_id: str,
        purpose: str,
        consent_types: Optional[List[ConsentType]] = None
    ) -> bool:
        """
        Check if valid consent exists for purpose
        
        Args:
            session_id: Session identifier
            purpose: Purpose for data processing
            consent_types: Optional specific consent types to check
        
        Returns:
            True if valid consent exists
        """
        
        if consent_types is None:
            consent_types = self.REQUIRED_CONSENT_BY_PURPOSE.get(purpose, [])
        
        async with self.postgres.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT *
                FROM consent_records
                WHERE session_id = $1
                AND purpose = $2
                AND status = 'granted'
                AND (expires_at IS NULL OR expires_at > NOW())
                ORDER BY granted_at DESC
                LIMIT 1
                """,
                session_id,
                purpose
            )
        
        if not row:
            logger.warning(
                f"⚠️  No valid consent found:\n"
                f"   Session: {session_id}\n"
                f"   Purpose: {purpose}"
            )
            return False
        
        # Check all required consent types are present
        granted_types = [ConsentType(t) for t in row["consent_types"]]
        
        for required_type in consent_types:
            if required_type not in granted_types:
                logger.warning(
                    f"⚠️  Missing consent type:\n"
                    f"   Session: {session_id}\n"
                    f"   Purpose: {purpose}\n"
                    f"   Missing: {required_type.value}"
                )
                return False
        
        return True
    
    async def get_consent_audit_trail(
        self,
        session_id: str
    ) -> List[ConsentRequest]:
        """
        Get complete consent audit trail for session
        
        Args:
            session_id: Session identifier
        
        Returns:
            List of consent records
        """
        
        async with self.postgres.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT *
                FROM consent_records
                WHERE session_id = $1
                ORDER BY requested_at DESC
                """,
                session_id
            )
        
        return [self._row_to_consent(row) for row in rows]
    
    def _generate_consent_text(
        self,
        purpose: str,
        consent_types: List[ConsentType],
        jurisdiction: str
    ) -> str:
        """Generate clear, understandable consent text"""
        
        purpose_description = self.VALID_PURPOSES[purpose]
        
        # Base consent text
        text = f"""
# Consent for Video and Liveness Verification

## Purpose
We need your consent to: **{purpose_description}**

## What We'll Do
By consenting, you allow us to:
"""
        
        # Add specific consent types
        consent_descriptions = {
            ConsentType.VIDEO_CAPTURE: "- **Capture video** of your face during verification",
            ConsentType.LIVENESS_DETECTION: "- **Analyze your facial movements** to confirm you're a real person",
            ConsentType.BIOMETRIC_PROCESSING: "- **Process biometric-adjacent data** derived from your facial movements (not stored)",
            ConsentType.DATA_STORAGE: "- **Temporarily store verification data** for the purpose stated above",
            ConsentType.DATA_ANALYSIS: "- **Analyze verification data** to improve our service"
        }
        
        for consent_type in consent_types:
            text += f"\n{consent_descriptions[consent_type]}"
        
        # Add data protection info
        text += """

## Your Rights
- You can **withdraw consent** at any time
- We will **delete your data** if you withdraw consent
- Your data is **encrypted** and securely stored
- We will **never sell** your data to third parties

## Data Retention
- Verification data: Deleted after 90 days
- Audit logs: Retained for 7 years (legal requirement)

## Questions?
Contact our privacy team at privacy@certivo.com
"""
        
        # Add jurisdiction-specific info
        if jurisdiction in ["eu", "uk"]:
            text += """

## GDPR Rights
Under GDPR, you have the right to:
- Access your data
- Rectify incorrect data
- Erase your data
- Restrict processing
- Data portability
- Object to processing

Contact: dpo@certivo.com
"""
        
        elif jurisdiction == "us_ca":
            text += """

## CCPA Rights
Under CCPA, you have the right to:
- Know what personal information we collect
- Delete your personal information
- Opt-out of sale (we never sell your data)
- Non-discrimination for exercising rights

Contact: privacy@certivo.com
"""
        
        return text.strip()
    
    async def _handle_consent_withdrawal(self, consent_id: str):
        """Handle data deletion after consent withdrawal"""
        
        # Get consent details
        async with self.postgres.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM consent_records WHERE consent_id = $1",
                consent_id
            )
        
        if not row:
            return
        
        session_id = row["session_id"]
        consent_types = row["consent_types"]
        
        # If video/data storage consent withdrawn, trigger deletion
        if "data_storage" in consent_types or "video_capture" in consent_types:
            logger.info(
                f"🗑️  Triggering data deletion for consent withdrawal:\n"
                f"   Consent ID: {consent_id}\n"
                f"   Session: {session_id}"
            )
            
            # This would integrate with the deletion engine from Part 7.2
            # For now, log the requirement
            async with self.postgres.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO deletion_jobs (
                        job_id,
                        deletion_type,
                        table_name,
                        initiated_by
                    )
                    VALUES (
                        $1,
                        'user_request',
                        'sessions',
                        $2
                    )
                    """,
                    f"DEL-CONSENT-{consent_id}",
                    f"consent_withdrawal:{consent_id}"
                )
    
    def _row_to_consent(self, row: Dict[str, Any]) -> ConsentRequest:
        """Convert database row to ConsentRequest"""
        
        return ConsentRequest(
            consent_id=row["consent_id"],
            session_id=row["session_id"],
            user_identifier=row["user_identifier"],
            consent_types=[ConsentType(t) for t in row["consent_types"]],
            purpose=row["purpose"],
            jurisdiction=row["jurisdiction"],
            status=ConsentStatus(row["status"]),
            consent_text=row["consent_text"],
            consent_version=row["consent_version"],
            granted_at=row.get("granted_at"),
            denied_at=row.get("denied_at"),
            withdrawn_at=row.get("withdrawn_at"),
            requested_at=row["requested_at"],
            ip_address=row["ip_address"],
            user_agent=row["user_agent"],
            expires_at=row.get("expires_at")
        )