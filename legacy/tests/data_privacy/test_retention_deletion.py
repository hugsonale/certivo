"""
Retention and Deletion Tests

Acceptance Criteria:
1. Deletion request completed within 30 days
2. Deletion is verifiable in logs and storage checks
"""

import pytest
import asyncio
import asyncpg
from datetime import datetime, timedelta
import sys
import os

sys.path.insert(0, 'services/data_privacy')

from retention_policy_engine import (
    RetentionPolicyEngine,
    Jurisdiction,
    RetentionWindow
)
from deletion_engine import (
    DeletionEngine,
    DeletionType,
    DeletionStatus
)
from user_erasure_service import (
    UserErasureService,
    ErasureStatus
)


class TestRetentionPolicies:
    """Test retention policy configuration"""
    
    @pytest.fixture
    async def postgres_pool(self):
        """Setup test database connection"""
        pool = await asyncpg.create_pool(
            "postgresql://certivo:certivo@localhost:5432/certivo_test"
        )
        yield pool
        await pool.close()
    
    @pytest.fixture
    async def retention_engine(self, postgres_pool):
        """Setup retention policy engine"""
        return RetentionPolicyEngine(postgres_pool)
    
    @pytest.mark.asyncio
    async def test_retention_policy_configuration(self, retention_engine):
        """Test jurisdiction-specific retention policies"""
        
        print("\n" + "="*60)
        print("TEST: Retention Policy Configuration")
        print("="*60)
        
        # Test default retention for different jurisdictions
        jurisdictions = [
            (Jurisdiction.EU, 90),
            (Jurisdiction.US_CALIFORNIA, 90),
            (Jurisdiction.US_OTHER, 180),
            (Jurisdiction.UK, 90),
            (Jurisdiction.CANADA, 90),
            (Jurisdiction.AUSTRALIA, 90),
            (Jurisdiction.JAPAN, 180),
            (Jurisdiction.GLOBAL, 90)
        ]
        
        print("\n✓ Testing default retention windows:")
        
        for jurisdiction, expected_days in jurisdictions:
            window = await retention_engine.get_retention_window(
                table_name="sessions",
                jurisdiction=jurisdiction
            )
            
            print(f"  {jurisdiction.value}: {window.retention_days} days")
            
            assert window.retention_days == expected_days, \
                f"Expected {expected_days} days for {jurisdiction.value}"
        
        print("\n✅ Retention policy configuration test passed")
    
    @pytest.mark.asyncio
    async def test_tenant_specific_retention(self, retention_engine):
        """Test tenant-specific retention overrides"""
        
        print("\n" + "="*60)
        print("TEST: Tenant-Specific Retention")
        print("="*60)
        
        # Set custom retention for tenant
        tenant_id = "TENANT-TEST-001"
        
        await retention_engine.set_retention_policy(
            table_name="verification_results",
            jurisdiction=Jurisdiction.EU,
            retention_days=180,  # Override default 90
            tenant_id=tenant_id,
            created_by="test_admin"
        )
        
        # Get retention window
        window = await retention_engine.get_retention_window(
            table_name="verification_results",
            jurisdiction=Jurisdiction.EU,
            tenant_id=tenant_id
        )
        
        print(f"\n✓ Custom Retention Set:")
        print(f"  Tenant: {tenant_id}")
        print(f"  Table: verification_results")
        print(f"  Retention: {window.retention_days} days")
        print(f"  Custom: {window.custom_retention}")
        
        assert window.retention_days == 180
        assert window.custom_retention == True
        assert window.tenant_id == tenant_id
        
        print("\n✅ Tenant-specific retention test passed")
    
    @pytest.mark.asyncio
    async def test_legal_hold(self, retention_engine):
        """Test legal hold functionality"""
        
        print("\n" + "="*60)
        print("TEST: Legal Hold")
        print("="*60)
        
        tenant_id = "TENANT-LEGAL-001"
        
        # Set retention policy
        await retention_engine.set_retention_policy(
            table_name="sessions",
            jurisdiction=Jurisdiction.EU,
            retention_days=90,
            tenant_id=tenant_id,
            created_by="test_admin"
        )
        
        # Place legal hold
        await retention_engine.set_legal_hold(
            table_name="sessions",
            jurisdiction=Jurisdiction.EU,
            tenant_id=tenant_id,
            reason="Ongoing litigation - Case #12345",
            created_by="legal_team"
        )
        
        print("\n✓ Legal hold placed")
        print(f"  Tenant: {tenant_id}")
        print(f"  Reason: Ongoing litigation")
        
        # Try to get records for deletion (should be empty due to legal hold)
        tables = await retention_engine.get_tables_for_deletion(
            jurisdiction=Jurisdiction.EU,
            tenant_id=tenant_id
        )
        
        # Legal hold should prevent deletion
        sessions_ready = [t for t in tables if t["table_name"] == "sessions"]
        
        assert len(sessions_ready) == 0, \
            "Legal hold should prevent deletion"
        
        print("✓ Legal hold prevents deletion as expected")
        
        # Release legal hold
        await retention_engine.release_legal_hold(
            table_name="sessions",
            jurisdiction=Jurisdiction.EU,
            tenant_id=tenant_id,
            released_by="legal_team"
        )
        
        print("✓ Legal hold released")
        
        print("\n✅ Legal hold test passed")


class TestDeletionEngine:
    """Test automatic deletion engine"""
    
    @pytest.fixture
    async def postgres_pool(self):
        """Setup test database connection"""
        pool = await asyncpg.create_pool(
            "postgresql://certivo:certivo@localhost:5432/certivo_test"
        )
        yield pool
        await pool.close()
    
    @pytest.fixture
    async def deletion_engine(self, postgres_pool):
        """Setup deletion engine"""
        return DeletionEngine(
            postgres_pool=postgres_pool,
            s3_bucket="certivo-test-videos",
            aws_region="us-east-1"
        )
    
    @pytest.mark.asyncio
    async def test_automatic_deletion_job(self, deletion_engine, postgres_pool):
        """Test automatic deletion job creation and execution"""
        
        print("\n" + "="*60)
        print("TEST: Automatic Deletion Job")
        print("="*60)
        
        # Insert test data
        print("\n✓ Creating test data...")
        
        async with postgres_pool.acquire() as conn:
            # Create old sessions (91 days ago)
            old_date = datetime.utcnow() - timedelta(days=91)
            
            await conn.execute(
                """
                INSERT INTO sessions (
                    session_id, device_id, ip_address, created_at
                )
                VALUES 
                    ('TEST-OLD-001', 'device-001', '127.0.0.1', $1),
                    ('TEST-OLD-002', 'device-002', '127.0.0.2', $1),
                    ('TEST-OLD-003', 'device-003', '127.0.0.3', $1)
                """,
                old_date
            )
            
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM sessions WHERE session_id LIKE 'TEST-OLD-%'"
            )
        
        print(f"  Created {count} old sessions")
        
        # Create deletion job
        print("\n✓ Creating deletion job...")
        
        job = await deletion_engine.create_deletion_job(
            deletion_type=DeletionType.AUTOMATIC,
            table_name="sessions",
            initiated_by="test_system"
        )
        
        print(f"  Job ID: {job.job_id}")
        print(f"  Status: {job.status.value}")
        
        # Execute deletion
        print("\n✓ Executing deletion...")
        
        completed_job = await deletion_engine.execute_deletion_job(
            job_id=job.job_id,
            retention_days=90
        )
        
        print(f"  Status: {completed_job.status.value}")
        print(f"  Records identified: {completed_job.records_identified}")
        print(f"  Records deleted: {completed_job.records_deleted}")
        print(f"  Records failed: {completed_job.records_failed}")
        
        # Verify deletion
        async with postgres_pool.acquire() as conn:
            remaining = await conn.fetchval(
                """
                SELECT COUNT(*)
                FROM sessions
                WHERE session_id LIKE 'TEST-OLD-%'
                AND deleted_at IS NULL
                """
            )
        
        print(f"  Records remaining: {remaining}")
        
        assert completed_job.status == DeletionStatus.COMPLETED
        assert completed_job.records_deleted > 0
        assert remaining == 0, "All old records should be deleted"
        
        print("\n✅ Automatic deletion job test passed")


class TestUserErasure:
    """
    Test user erasure workflow
    
    ACCEPTANCE CRITERIA 1: Deletion completed within 30 days
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
    async def deletion_engine(self, postgres_pool):
        """Setup deletion engine"""
        return DeletionEngine(
            postgres_pool=postgres_pool,
            s3_bucket="certivo-test-videos",
            aws_region="us-east-1"
        )
    
    @pytest.fixture
    async def erasure_service(self, postgres_pool, deletion_engine):
        """Setup user erasure service"""
        return UserErasureService(
            postgres_pool=postgres_pool,
            deletion_engine=deletion_engine
        )
    
    @pytest.mark.asyncio
    async def test_user_erasure_workflow(
        self,
        erasure_service,
        postgres_pool
    ):
        """
        ACCEPTANCE CRITERIA 1: Deletion completed within 30 days
        
        Test complete user erasure workflow
        """
        
        print("\n" + "="*60)
        print("ACCEPTANCE TEST: User Erasure Workflow (30-Day SLA)")
        print("="*60)
        
        user_identifier = "test-user@example.com"
        user_email = "test-user@example.com"
        
        # Step 1: Create test user data
        print("\n✓ Step 1: Creating test user data...")
        
        async with postgres_pool.acquire() as conn:
            # Create session
            await conn.execute(
                """
                INSERT INTO sessions (
                    session_id, user_identifier, device_id, ip_address
                )
                VALUES ('TEST-SESSION-001', $1, 'test-device', '127.0.0.1')
                """,
                user_identifier
            )
            
            # Create verification result
            await conn.execute(
                """
                INSERT INTO verification_results (
                    verification_id, session_id, liveness_score, decision
                )
                VALUES ('TEST-VERIFY-001', 'TEST-SESSION-001', 0.95, 'approve')
                """
            )
            
            # Count user records
            session_count = await conn.fetchval(
                "SELECT COUNT(*) FROM sessions WHERE user_identifier = $1",
                user_identifier
            )
            
            result_count = await conn.fetchval(
                """
                SELECT COUNT(*) FROM verification_results
                WHERE session_id = 'TEST-SESSION-001'
                """
            )
        
        print(f"  Sessions created: {session_count}")
        print(f"  Verification results created: {result_count}")
        
        # Step 2: Initiate erasure request
        print("\n✓ Step 2: Initiating erasure request...")
        
        request = await erasure_service.initiate_user_erasure(
            user_identifier=user_identifier,
            user_email=user_email,
            request_source="api"
        )
        
        print(f"  Request ID: {request.request_id}")
        print(f"  Status: {request.status.value}")
        print(f"  Deadline: {request.deadline.isoformat()}")
        
        days_until_deadline = (request.deadline - request.requested_at).days
        
        print(f"  SLA: {days_until_deadline} days")
        
        assert days_until_deadline == 30, "SLA should be 30 days"
        assert request.status == ErasureStatus.ACKNOWLEDGED
        
        # Step 3: Execute erasure
        print("\n✓ Step 3: Executing erasure...")
        
        completed_request = await erasure_service.execute_user_erasure(
            request_id=request.request_id
        )
        
        print(f"  Status: {completed_request.status.value}")
        print(f"  Tables processed: {len(completed_request.tables_completed)}")
        print(f"  Records deleted: {completed_request.total_records_deleted}")
        
        # Calculate duration
        duration = completed_request.completed_at - completed_request.requested_at
        duration_days = duration.days
        duration_hours = duration.seconds // 3600
        duration_minutes = (duration.seconds % 3600) // 60
        
        print(f"  Duration: {duration_days} days, {duration_hours} hours, {duration_minutes} minutes")
        
        # Step 4: Verify erasure
        print("\n✓ Step 4: Verifying erasure...")
        
        async with postgres_pool.acquire() as conn:
            remaining_sessions = await conn.fetchval(
                """
                SELECT COUNT(*)
                FROM sessions
                WHERE user_identifier = $1
                AND deleted_at IS NULL
                """,
                user_identifier
            )
            
            remaining_results = await conn.fetchval(
                """
                SELECT COUNT(*)
                FROM verification_results
                WHERE session_id = 'TEST-SESSION-001'
                AND deleted_at IS NULL
                """
            )
            
            # Check audit log
            audit_count = await conn.fetchval(
                """
                SELECT COUNT(*)
                FROM deletion_audit_log
                WHERE deleted_at >= $1
                """,
                completed_request.started_at
            )
        
        print(f"  Remaining sessions: {remaining_sessions}")
        print(f"  Remaining results: {remaining_results}")
        print(f"  Audit log entries: {audit_count}")
        
        # Verify verification results
        verification = completed_request.verification_results
        
        print(f"  Verification passed: {verification['verified']}")
        print(f"  Tables checked: {len(verification['tables_checked'])}")
        
        print("\n" + "="*60)
        print("ACCEPTANCE CRITERIA VALIDATION")
        print("="*60)
        
        # Criterion 1: Completed within 30 days
        within_sla = duration_days <= 30
        
        print(f"\n✓ Criterion 1: Deletion completed within 30 days")
        print(f"  Target: ≤30 days")
        print(f"  Actual: {duration_days} days")
        print(f"  Result: {'✅ PASS' if within_sla else '❌ FAIL'}")
        
        assert within_sla, f"Erasure took {duration_days} days, exceeds 30-day SLA"
        
        # Criterion 2: Verifiable in logs
        print(f"\n✓ Criterion 2: Deletion verifiable in logs and storage")
        print(f"  Database records remaining: {remaining_sessions + remaining_results}")
        print(f"  Audit log entries: {audit_count}")
        print(f"  Verification completed: {verification['verified']}")
        print(f"  Result: {'✅ PASS' if verification['verified'] else '❌ FAIL'}")
        
        assert remaining_sessions == 0, "Sessions should be deleted"
        assert remaining_results == 0, "Verification results should be deleted"
        assert audit_count >= completed_request.total_records_deleted, \
            "All deletions should be in audit log"
        assert verification['verified'], "Verification should pass"
        
        print("\n" + "="*60)
        print("✅ ALL ACCEPTANCE CRITERIA MET")
        print("="*60)
        print(f"\n  ✅ Deletion completed in {duration_days} days (within 30-day SLA)")
        print(f"  ✅ All records deleted: {completed_request.total_records_deleted}")
        print(f"  ✅ Audit log complete: {audit_count} entries")
        print(f"  ✅ Storage verification passed")
        print("="*60)


class TestDeletionVerification:
    """
    Test deletion verification
    
    ACCEPTANCE CRITERIA 2: Deletion is verifiable in logs and storage checks
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
    async def deletion_engine(self, postgres_pool):
        """Setup deletion engine"""
        return DeletionEngine(
            postgres_pool=postgres_pool,
            s3_bucket="certivo-test-videos",
            aws_region="us-east-1"
        )
    
    @pytest.mark.asyncio
    async def test_deletion_verification(self, deletion_engine, postgres_pool):
        """
        ACCEPTANCE CRITERIA 2: Deletion is verifiable
        
        Test multi-layer deletion verification:
        1. Database records deleted
        2. S3 objects removed
        3. Audit log entries created
        """
        
        print("\n" + "="*60)
        print("ACCEPTANCE TEST: Deletion Verification")
        print("="*60)
        
        # Create test data
        print("\n✓ Creating test data...")
        
        async with postgres_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO sessions (
                    session_id, device_id, ip_address
                )
                VALUES 
                    ('VERIFY-001', 'device-001', '127.0.0.1'),
                    ('VERIFY-002', 'device-002', '127.0.0.2')
                """
            )
        
        # Create deletion job
        job = await deletion_engine.create_deletion_job(
            deletion_type=DeletionType.AUTOMATIC,
            table_name="sessions",
            initiated_by="test_verification"
        )
        
        # Execute deletion
        print("\n✓ Executing deletion...")
        
        completed_job = await deletion_engine.execute_deletion_job(
            job_id=job.job_id,
            retention_days=0  # Delete all test records
        )
        
        print(f"  Records deleted: {completed_job.records_deleted}")
        
        # Verify deletion
        print("\n✓ Verifying deletion...")
        
        verification = await deletion_engine.verify_deletion(job.job_id)
        
        print("\n📊 Verification Results:")
        print(f"  Overall: {'✅ VERIFIED' if verification['verified'] else '❌ FAILED'}")
        
        for check_name, check_result in verification['checks'].items():
            status = "✅ PASS" if check_result['passed'] else "❌ FAIL"
            print(f"\n  {check_name}: {status}")
            
            if isinstance(check_result, dict):
                for key, value in check_result.items():
                    if key != 'passed':
                        print(f"    {key}: {value}")
        
        print("\n" + "="*60)
        print("ACCEPTANCE CRITERIA VALIDATION")
        print("="*60)
        
        print("\n✓ Criterion 2: Deletion is verifiable")
        
        # Check 1: Database verification
        db_check = verification['checks']['record_count']
        print(f"\n  Database Verification:")
        print(f"    Records identified: {db_check['identified']}")
        print(f"    Records deleted: {db_check['deleted']}")
        print(f"    Records failed: {db_check['failed']}")
        print(f"    Status: {'✅ PASS' if db_check['passed'] else '❌ FAIL'}")
        
        # Check 2: Audit log verification
        audit_check = verification['checks']['audit_log']
        print(f"\n  Audit Log Verification:")
        print(f"    Expected minimum: {audit_check['expected_minimum']}")
        print(f"    Actual entries: {audit_check['actual']}")
        print(f"    Status: {'✅ PASS' if audit_check['passed'] else '❌ FAIL'}")
        
        # Check 3: Overall verification
        print(f"\n  Overall Verification:")
        print(f"    Status: {'✅ VERIFIED' if verification['verified'] else '❌ FAILED'}")
        
        assert verification['verified'], "Deletion verification failed"
        
        print("\n" + "="*60)
        print("✅ ACCEPTANCE CRITERIA MET: Deletion Verifiable")
        print("="*60)


class TestSLACompliance:
    """Test SLA compliance for deletions"""
    
    @pytest.fixture
    async def postgres_pool(self):
        """Setup test database connection"""
        pool = await asyncpg.create_pool(
            "postgresql://certivo:certivo@localhost:5432/certivo_test"
        )
        yield pool
        await pool.close()
    
    @pytest.mark.asyncio
    async def test_deletion_sla_compliance(self, postgres_pool):
        """Test that deletions complete within SLA"""
        
        print("\n" + "="*60)
        print("TEST: Deletion SLA Compliance")
        print("="*60)
        
        # Create mock erasure requests with different timelines
        async with postgres_pool.acquire() as conn:
            # Request 1: Completed within SLA (28 days)
            await conn.execute(
                """
                INSERT INTO data_subject_requests (
                    request_id,
                    request_type,
                    subject_identifier_hash,
                    status,
                    requested_at,
                    completed_at,
                    deadline
                )
                VALUES (
                    'SLA-TEST-001',
                    'deletion',
                    'hash_001',
                    'completed',
                    NOW() - INTERVAL '28 days',
                    NOW(),
                    NOW() + INTERVAL '2 days'
                )
                """
            )
            
            # Request 2: Still in progress (15 days)
            await conn.execute(
                """
                INSERT INTO data_subject_requests (
                    request_id,
                    request_type,
                    subject_identifier_hash,
                    status,
                    requested_at,
                    deadline
                )
                VALUES (
                    'SLA-TEST-002',
                    'deletion',
                    'hash_002',
                    'in_progress',
                    NOW() - INTERVAL '15 days',
                    NOW() + INTERVAL '15 days'
                )
                """
            )
            
            # Check SLA status
            sla_status = await conn.fetch(
                "SELECT * FROM check_deletion_sla()"
            )
        
        print("\n📊 SLA Status:")
        
        for status in sla_status:
            print(f"\n  Request: {status['request_id']}")
            print(f"    Status: {status['status']}")
            print(f"    Days remaining: {status['days_remaining']}")
            print(f"    Overdue: {status['overdue']}")
            
            # Verify none are overdue
            if status['status'] == 'completed':
                assert not status['overdue'], \
                    f"Completed request should not be overdue"
        
        print("\n✅ SLA compliance test passed")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])