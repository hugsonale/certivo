"""
Consent and Access Control Tests

Acceptance Criteria:
1. Quarterly access review complete
2. No broad wildcard storage access in production roles
"""

import pytest
import asyncio
import asyncpg
from datetime import datetime, timedelta
import sys

sys.path.insert(0, 'services/legal')
sys.path.insert(0, 'services/security')

from consent_manager import (
    ConsentManager,
    ConsentType,
    ConsentStatus
)
from purpose_limitation import (
    PurposeLimitationEnforcer,
    DataPurpose
)
from access_control_manager import (
    AccessControlManager,
    Role,
    Permission
)


class TestConsentManagement:
    """Test consent capture and management"""
    
    @pytest.fixture
    async def postgres_pool(self):
        """Setup test database connection"""
        pool = await asyncpg.create_pool(
            "postgresql://certivo:certivo@localhost:5432/certivo_test"
        )
        yield pool
        await pool.close()
    
    @pytest.fixture
    async def consent_manager(self, postgres_pool):
        """Setup consent manager"""
        return ConsentManager(postgres_pool)
    
    @pytest.mark.asyncio
    async def test_consent_request_and_grant(self, consent_manager):
        """Test explicit consent capture"""
        
        print("\n" + "="*60)
        print("TEST: Explicit Consent Capture")
        print("="*60)
        
        session_id = "TEST-SESSION-CONSENT-001"
        
        # Request consent
        print("\n✓ Step 1: Requesting consent...")
        
        consent_request = await consent_manager.request_consent(
            session_id=session_id,
            purpose="identity_verification",
            jurisdiction="eu",
            user_identifier="test-user@example.com",
            ip_address="127.0.0.1",
            user_agent="Mozilla/5.0"
        )
        
        print(f"  Consent ID: {consent_request.consent_id}")
        print(f"  Purpose: {consent_request.purpose}")
        print(f"  Types: {', '.join([ct.value for ct in consent_request.consent_types])}")
        print(f"  Status: {consent_request.status.value}")
        
        assert consent_request.status == ConsentStatus.PENDING
        assert ConsentType.VIDEO_CAPTURE in consent_request.consent_types
        assert ConsentType.LIVENESS_DETECTION in consent_request.consent_types
        
        # Grant consent
        print("\n✓ Step 2: Granting consent...")
        
        granted = await consent_manager.grant_consent(
            consent_id=consent_request.consent_id,
            user_acknowledgment="I agree to the terms stated above"
        )
        
        print(f"  Status: {granted.status.value}")
        print(f"  Granted at: {granted.granted_at.isoformat()}")
        
        assert granted.status == ConsentStatus.GRANTED
        assert granted.granted_at is not None
        
        # Verify consent
        print("\n✓ Step 3: Verifying consent...")
        
        has_consent = await consent_manager.check_consent(
            session_id=session_id,
            purpose="identity_verification"
        )
        
        print(f"  Has valid consent: {has_consent}")
        
        assert has_consent == True
        
        print("\n✅ Explicit consent capture test passed")
    
    @pytest.mark.asyncio
    async def test_consent_withdrawal(self, consent_manager):
        """Test consent withdrawal (GDPR Article 7(3))"""
        
        print("\n" + "="*60)
        print("TEST: Consent Withdrawal")
        print("="*60)
        
        session_id = "TEST-SESSION-WITHDRAW-001"
        
        # Grant consent
        consent_request = await consent_manager.request_consent(
            session_id=session_id,
            purpose="identity_verification",
            jurisdiction="eu"
        )
        
        await consent_manager.grant_consent(
            consent_id=consent_request.consent_id,
            user_acknowledgment="I agree"
        )
        
        print("\n✓ Consent granted")
        
        # Withdraw consent
        print("\n✓ Withdrawing consent...")
        
        withdrawn = await consent_manager.withdraw_consent(
            consent_id=consent_request.consent_id,
            reason="User changed mind"
        )
        
        print(f"  Status: {withdrawn.status.value}")
        print(f"  Withdrawn at: {withdrawn.withdrawn_at.isoformat()}")
        
        assert withdrawn.status == ConsentStatus.WITHDRAWN
        
        # Verify consent no longer valid
        has_consent = await consent_manager.check_consent(
            session_id=session_id,
            purpose="identity_verification"
        )
        
        print(f"  Has valid consent: {has_consent}")
        
        assert has_consent == False
        
        print("\n✅ Consent withdrawal test passed")


class TestPurposeLimitation:
    """Test purpose limitation enforcement"""
    
    def test_purpose_limitation_validation(self):
        """Test data access validation by purpose"""
        
        print("\n" + "="*60)
        print("TEST: Purpose Limitation Enforcement")
        print("="*60)
        
        enforcer = PurposeLimitationEnforcer()
        
        # Test 1: Valid access
        print("\n✓ Test 1: Valid data access")
        
        result = enforcer.validate_data_access(
            purpose=DataPurpose.IDENTITY_VERIFICATION,
            table_name="verification_results",
            fields_requested=["verification_id", "liveness_score", "decision"]
        )
        
        print(f"  Allowed: {result['allowed']}")
        print(f"  Fields: {', '.join(result['allowed_fields'])}")
        
        assert result["allowed"] == True
        
        # Test 2: Invalid access - table not allowed for purpose
        print("\n✓ Test 2: Invalid access - wrong table")
        
        result = enforcer.validate_data_access(
            purpose=DataPurpose.SERVICE_IMPROVEMENT,
            table_name="verification_results",  # Not allowed for service improvement
            fields_requested=["verification_id", "decision"]
        )
        
        print(f"  Allowed: {result['allowed']}")
        print(f"  Reason: {result['reason']}")
        
        assert result["allowed"] == False
        
        # Test 3: Invalid access - field not allowed
        print("\n✓ Test 3: Invalid access - disallowed field")
        
        result = enforcer.validate_data_access(
            purpose=DataPurpose.IDENTITY_VERIFICATION,
            table_name="verification_results",
            fields_requested=["verification_id", "internal_debug_data"]  # Not allowed
        )
        
        print(f"  Allowed: {result['allowed']}")
        print(f"  Disallowed fields: {', '.join(result.get('disallowed_fields', []))}")
        
        assert result["allowed"] == False
        
        print("\n✅ Purpose limitation test passed")


class TestAccessControl:
    """
    Test access control and quarterly reviews
    
    ACCEPTANCE CRITERIA:
    1. Quarterly access review complete
    2. No broad wildcard storage access
    """
    
    @pytest.fixture
    async def postgres_pool(self):
        """Setup test database connection"""
        pool = await asyncpg.create_pool(
            "postgresql://certivo:certivo@localhost:5432/certivo_test"
        )
        yield pool
        await pool.close()
    
    @pytest.fixture
    async def access_manager(self, postgres_pool):
        """Setup access control manager"""
        return AccessControlManager(postgres_pool)
    
    @pytest.mark.asyncio
    async def test_grant_access_least_privilege(self, access_manager):
        """Test granting access with least privilege"""
        
        print("\n" + "="*60)
        print("TEST: Least Privilege Access Grant")
        print("="*60)
        
        # Grant viewer access (least privilege)
        print("\n✓ Granting VIEWER access...")
        
        user_access = await access_manager.grant_access(
            user_id="user-001",
            user_email="viewer@example.com",
            role=Role.VIEWER,
            granted_by="admin@certivo.com",
            business_justification="View verification results for support",
            duration_days=90
        )
        
        print(f"  User: {user_access.user_email}")
        print(f"  Role: {user_access.role.value}")
        print(f"  Permissions: {len(user_access.permissions)}")
        print(f"  Expires: {user_access.expires_at.isoformat()}")
        print(f"  Next review: {user_access.next_review_due.isoformat()}")
        
        # Verify permissions are limited
        assert Permission.READ_SESSIONS in user_access.permissions
        assert Permission.READ_VERIFICATIONS in user_access.permissions
        assert Permission.WRITE_VERIFICATIONS not in user_access.permissions
        assert Permission.MANAGE_USERS not in user_access.permissions
        
        # Verify review is scheduled (quarterly = 90 days)
        days_to_review = (user_access.next_review_due - user_access.granted_at).days
        assert days_to_review == 90
        
        print("\n✅ Least privilege access grant test passed")
    
    @pytest.mark.asyncio
    async def test_wildcard_prevention(self, access_manager):
        """
        ACCEPTANCE CRITERIA 2: No wildcard storage access
        
        Test that wildcard permissions are blocked
        """
        
        print("\n" + "="*60)
        print("ACCEPTANCE TEST: No Wildcard Storage Access")
        print("="*60)
        
        # Try to grant access with wildcard permission (should fail)
        print("\n✓ Testing wildcard prevention...")
        
        try:
            # Temporarily add wildcard permission to role (should be caught)
            from access_control_manager import RoleDefinition, Role, Permission
            
            # Create a test role with wildcard
            test_role_def = RoleDefinition(
                role=Role.ADMIN,
                description="Test role with wildcard",
                permissions={
                    Permission.READ_SESSIONS,
                    Permission("read:video:*")  # WILDCARD - should be blocked
                }
            )
            
            # This should raise ValueError
            access_manager.ROLE_DEFINITIONS[Role.ADMIN] = test_role_def
            
            await access_manager.grant_access(
                user_id="user-wildcard-test",
                user_email="wildcard@example.com",
                role=Role.ADMIN,
                granted_by="admin@certivo.com",
                business_justification="Test wildcard"
            )
            
            # Should not reach here
            assert False, "Wildcard permission should have been blocked"
            
        except ValueError as e:
            print(f"  ✅ Wildcard blocked: {str(e)[:100]}...")
            assert "WILDCARD PERMISSION DETECTED" in str(e)
        
        # Validate no wildcards in database
        print("\n✓ Validating database...")
        
        report = await access_manager.validate_no_wildcards()
        
        print(f"  Users checked: {report['total_users_checked']}")
        print(f"  Violations found: {report['violations_found']}")
        print(f"  Compliant: {report['compliant']}")
        
        assert report["compliant"] == True, "Wildcard permissions detected!"
        
        print("\n" + "="*60)
        print("✅ ACCEPTANCE CRITERIA MET: No Wildcard Storage Access")
        print("="*60)
    
    @pytest.mark.asyncio
    async def test_quarterly_review_workflow(self, access_manager):
        """
        ACCEPTANCE CRITERIA 1: Quarterly access review
        
        Test quarterly review workflow
        """
        
        print("\n" + "="*60)
        print("ACCEPTANCE TEST: Quarterly Access Review")
        print("="*60)
        
        # Grant access to test user
        print("\n✓ Step 1: Granting access...")
        
        user_access = await access_manager.grant_access(
            user_id="user-review-test",
            user_email="review-test@example.com",
            role=Role.ANALYST,
            granted_by="admin@certivo.com",
            business_justification="Data analysis"
        )
        
        print(f"  User: {user_access.user_email}")
        print(f"  Next review: {user_access.next_review_due.isoformat()}")
        
        # Simulate review being due (move next_review_due to past)
        print("\n✓ Step 2: Simulating review due date...")
        
        async with access_manager.postgres.acquire() as conn:
            await conn.execute(
                """
                UPDATE user_access
                SET next_review_due = NOW() - INTERVAL '1 day'
                WHERE user_id = $1
                """,
                "user-review-test"
            )
        
        # Get users requiring review
        print("\n✓ Step 3: Getting users requiring review...")
        
        users_requiring_review = await access_manager.get_users_requiring_review()
        
        print(f"  Users requiring review: {len(users_requiring_review)}")
        
        review_user = next(
            (u for u in users_requiring_review if u.user_id == "user-review-test"),
            None
        )
        
        assert review_user is not None, "Test user should require review"
        
        print(f"  Found test user: {review_user.user_email}")
        
        # Complete review
        print("\n✓ Step 4: Completing access review...")
        
        await access_manager.complete_access_review(
            user_id="user-review-test",
            reviewed_by="manager@certivo.com",
            decision="approved",
            notes="Access still required for data analysis"
        )
        
        print("  Review completed: APPROVED")
        
        # Verify next review scheduled
        async with access_manager.postgres.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT last_reviewed, next_review_due
                FROM user_access
                WHERE user_id = $1
                """,
                "user-review-test"
            )
        
        print(f"  Last reviewed: {row['last_reviewed'].isoformat()}")
        print(f"  Next review: {row['next_review_due'].isoformat()}")
        
        # Verify next review is 90 days from now
        days_to_next_review = (row["next_review_due"] - row["last_reviewed"]).days
        
        assert days_to_next_review == 90, "Next review should be in 90 days"
        
        # Generate quarterly report
        print("\n✓ Step 5: Generating quarterly review report...")
        
        report = await access_manager.generate_quarterly_review_report()
        
        print(f"\n📊 Quarterly Review Report:")
        print(f"  Quarter: {report['quarter']}")
        print(f"  Total users: {report['total_active_users']}")
        print(f"  Requiring review: {report['requiring_review']['count']}")
        print(f"  Recently reviewed: {report['recently_reviewed']['count']}")
        
        print("\n" + "="*60)
        print("✅ ACCEPTANCE CRITERIA MET: Quarterly Access Review Complete")
        print("="*60)


class TestEncryption:
    """Test encryption configuration"""
    
    def test_tls_configuration(self):
        """Test TLS 1.2+ enforcement"""
        
        print("\n" + "="*60)
        print("TEST: TLS 1.2+ Enforcement")
        print("="*60)
        
        from infrastructure.security.tls_config import TLSConfigManager
        
        # Create SSL context
        print("\n✓ Creating TLS context...")
        
        context = TLSConfigManager.create_ssl_context()
        
        print(f"  Minimum version: {context.minimum_version}")
        print(f"  Certificate verification: {context.verify_mode}")
        print(f"  Hostname verification: {context.check_hostname}")
        
        # Verify minimum version
        import ssl
        assert context.minimum_version == ssl.TLSVersion.TLSv1_2
        
        # Verify certificate verification enabled
        assert context.verify_mode == ssl.CERT_REQUIRED
        assert context.check_hostname == True
        
        # Test version validation
        print("\n✓ Testing version validation...")
        
        assert TLSConfigManager.validate_tls_version("TLSv1.2") == True
        assert TLSConfigManager.validate_tls_version("TLSv1.3") == True
        assert TLSConfigManager.validate_tls_version("TLSv1.1") == False
        assert TLSConfigManager.validate_tls_version("TLSv1.0") == False
        
        print("\n✅ TLS 1.2+ enforcement test passed")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])