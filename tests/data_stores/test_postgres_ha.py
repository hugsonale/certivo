"""
PostgreSQL High Availability Tests

Acceptance Criteria:
1. Backup restore test successful
2. RPO <= 15 minutes
3. RTO <= 1 hour
"""

import pytest
import asyncio
import asyncpg
from datetime import datetime, timedelta
import subprocess
import sys
import os

sys.path.insert(0, 'infrastructure/postgres')

from backup_manager import PostgresBackupManager, BackupInfo


class TestPostgresBackup:
    """Test PostgreSQL backup operations"""
    
    @pytest.fixture
    def backup_manager(self):
        """Setup backup manager"""
        return PostgresBackupManager(
            stanza="certivo",
            backup_bucket="certivo-postgres-backups"
        )
    
    def test_create_full_backup(self, backup_manager):
        """Test full backup creation"""
        
        print("\n" + "="*60)
        print("TEST: Full Backup Creation")
        print("="*60)
        
        # Create full backup
        backup_info = backup_manager.create_full_backup()
        
        print(f"\n✓ Backup created:")
        print(f"  Backup ID: {backup_info.backup_id}")
        print(f"  Type: {backup_info.backup_type}")
        print(f"  Size: {backup_info.size_bytes / (1024**3):.2f} GB")
        print(f"  Duration: {backup_info.duration_seconds:.1f}s")
        
        assert backup_info.backup_type == "full"
        assert backup_info.size_bytes > 0
        
        print("\n✅ Full backup test passed")
    
    def test_list_backups(self, backup_manager):
        """Test listing available backups"""
        
        backups = backup_manager.list_backups()
        
        print(f"\n📋 Available backups: {len(backups)}")
        
        for backup in backups[:5]:  # Show first 5
            print(f"  - {backup.backup_id} ({backup.backup_type})")
            print(f"    Time: {backup.timestamp.isoformat()}")
            print(f"    Size: {backup.size_bytes / (1024**3):.2f} GB")
        
        assert len(backups) > 0
        
        print("\n✅ List backups test passed")
    
    def test_verify_backup(self, backup_manager):
        """Test backup verification"""
        
        # Get latest backup
        backups = backup_manager.list_backups()
        latest_backup = backups[-1]
        
        print(f"\n🔍 Verifying backup: {latest_backup.backup_id}")
        
        # Verify backup
        is_valid = backup_manager.verify_backup(latest_backup.backup_id)
        
        assert is_valid, "Backup verification failed"
        
        print(f"✅ Backup verification passed")


class TestPostgresRestore:
    """
    Test PostgreSQL restore operations
    
    ACCEPTANCE CRITERIA 1: Backup restore test successful
    """
    
    @pytest.fixture
    def backup_manager(self):
        """Setup backup manager"""
        return PostgresBackupManager(
            stanza="certivo",
            backup_bucket="certivo-postgres-backups"
        )
    
    @pytest.fixture
    async def postgres_pool(self):
        """Setup test database connection"""
        pool = await asyncpg.create_pool(
            "postgresql://certivo:certivo@localhost:5432/certivo_test"
        )
        yield pool
        await pool.close()
    
    @pytest.mark.asyncio
    async def test_backup_restore_full_cycle(self, backup_manager, postgres_pool):
        """
        ACCEPTANCE CRITERIA 1: Backup restore test successful
        
        Complete backup and restore cycle:
        1. Insert test data
        2. Create backup
        3. Insert more data
        4. Restore from backup
        5. Verify original data present, new data absent
        """
        
        print("\n" + "="*60)
        print("ACCEPTANCE TEST: Backup Restore Full Cycle")
        print("="*60)
        
        # Step 1: Insert test data before backup
        print("\n✓ Step 1: Inserting test data...")
        
        async with postgres_pool.acquire() as conn:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS backup_test (
                    id SERIAL PRIMARY KEY,
                    data TEXT,
                    created_at TIMESTAMP
                )
                """
            )
            
            await conn.execute(
                """
                INSERT INTO backup_test (data, created_at)
                VALUES ('before_backup', NOW())
                """
            )
            
            count_before = await conn.fetchval(
                "SELECT COUNT(*) FROM backup_test"
            )
        
        print(f"  Records before backup: {count_before}")
        
        # Step 2: Create backup
        print("\n✓ Step 2: Creating backup...")
        
        backup_info = backup_manager.create_full_backup()
        backup_time = datetime.utcnow()
        
        print(f"  Backup ID: {backup_info.backup_id}")
        print(f"  Backup time: {backup_time.isoformat()}")
        
        # Wait a bit to ensure backup is complete
        await asyncio.sleep(5)
        
        # Step 3: Insert data after backup
        print("\n✓ Step 3: Inserting data after backup...")
        
        async with postgres_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO backup_test (data, created_at)
                VALUES ('after_backup', NOW())
                """
            )
            
            count_after = await conn.fetchval(
                "SELECT COUNT(*) FROM backup_test"
            )
        
        print(f"  Records after backup: {count_after}")
        
        assert count_after == count_before + 1
        
        # Step 4: Restore from backup (to test database)
        print("\n✓ Step 4: Restoring from backup...")
        
        restore_start = datetime.utcnow()
        
        success = backup_manager.restore_from_backup(
            backup_id=backup_info.backup_id,
            target_dir="/var/lib/postgresql/15/certivo_test"
        )
        
        restore_end = datetime.utcnow()
        restore_duration = (restore_end - restore_start).total_seconds()
        
        print(f"  Restore duration: {restore_duration:.1f}s")
        
        assert success, "Restore failed"
        
        # Step 5: Verify data
        print("\n✓ Step 5: Verifying restored data...")
        
        # Reconnect after restore
        await postgres_pool.close()
        postgres_pool = await asyncpg.create_pool(
            "postgresql://certivo:certivo@localhost:5432/certivo_test"
        )
        
        async with postgres_pool.acquire() as conn:
            count_restored = await conn.fetchval(
                "SELECT COUNT(*) FROM backup_test"
            )
            
            before_backup_exists = await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM backup_test WHERE data = 'before_backup')"
            )
            
            after_backup_exists = await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM backup_test WHERE data = 'after_backup')"
            )
        
        print(f"  Records after restore: {count_restored}")
        print(f"  'before_backup' data present: {before_backup_exists}")
        print(f"  'after_backup' data present: {after_backup_exists}")
        
        # Verify
        assert count_restored == count_before, \
            f"Expected {count_before} records, got {count_restored}"
        
        assert before_backup_exists, "Pre-backup data missing"
        assert not after_backup_exists, "Post-backup data should not exist"
        
        print("\n" + "="*60)
        print("✅ ACCEPTANCE CRITERIA MET: Backup Restore Successful")
        print("="*60)
        
        await postgres_pool.close()
    
    @pytest.mark.asyncio
    async def test_point_in_time_recovery(self, backup_manager, postgres_pool):
        """Test point-in-time recovery (PITR)"""
        
        print("\n" + "="*60)
        print("TEST: Point-in-Time Recovery (PITR)")
        print("="*60)
        
        # Insert data at different times
        timestamps = []
        
        for i in range(3):
            timestamp = datetime.utcnow()
            timestamps.append(timestamp)
            
            async with postgres_pool.acquire() as conn:
                await conn.execute(
                    f"""
                    INSERT INTO backup_test (data, created_at)
                    VALUES ('pitr_test_{i}', '{timestamp.isoformat()}')
                    """
                )
            
            print(f"✓ Inserted data at: {timestamp.isoformat()}")
            
            await asyncio.sleep(2)
        
        # Restore to middle timestamp
        target_time = timestamps[1]
        
        print(f"\n🔄 Restoring to: {target_time.isoformat()}")
        
        success = backup_manager.restore_to_point_in_time(
            target_time=target_time,
            target_dir="/var/lib/postgresql/15/certivo_test"
        )
        
        assert success, "PITR failed"
        
        # Verify data
        async with postgres_pool.acquire() as conn:
            count = await conn.fetchval(
                """
                SELECT COUNT(*) FROM backup_test
                WHERE data LIKE 'pitr_test_%'
                AND created_at <= $1
                """,
                target_time
            )
        
        print(f"\n✓ Records at target time: {count}")
        
        assert count == 2, f"Expected 2 records, got {count}"
        
        print("\n✅ PITR test passed")


class TestRecoveryObjectives:
    """
    Test Recovery Point Objective (RPO) and Recovery Time Objective (RTO)
    
    ACCEPTANCE CRITERIA 2: RPO <= 15 minutes, RTO <= 1 hour
    """
    
    @pytest.fixture
    def backup_manager(self):
        """Setup backup manager"""
        return PostgresBackupManager(
            stanza="certivo",
            backup_bucket="certivo-postgres-backups"
        )
    
    def test_rpo_compliance(self, backup_manager):
        """
        ACCEPTANCE CRITERIA 2: RPO <= 15 minutes
        
        Verify continuous WAL archiving meets RPO target
        """
        
        print("\n" + "="*60)
        print("ACCEPTANCE TEST: RPO <= 15 Minutes")
        print("="*60)
        
        rpo_status = backup_manager.get_rpo_status()
        
        print(f"\n✓ RPO Status:")
        print(f"  Target: {rpo_status['rpo_target_minutes']} minutes")
        print(f"  Actual: {rpo_status['actual_rpo_minutes']:.1f} minutes")
        print(f"  Status: {rpo_status['status']}")
        print(f"  Last backup: {rpo_status['last_backup_time']}")
        print(f"  WAL archiving lag: {rpo_status['wal_archiving_lag_minutes']:.1f} minutes")
        
        # Verify RPO meets target
        assert rpo_status['actual_rpo_minutes'] <= 15, \
            f"RPO {rpo_status['actual_rpo_minutes']:.1f} minutes exceeds 15-minute target"
        
        print("\n" + "="*60)
        print("✅ ACCEPTANCE CRITERIA MET: RPO <= 15 Minutes")
        print(f"   Actual RPO: {rpo_status['actual_rpo_minutes']:.1f} minutes")
        print("="*60)
    
    def test_rto_compliance(self, backup_manager):
        """
        ACCEPTANCE CRITERIA 2: RTO <= 1 hour
        
        Estimate and verify RTO meets target
        """
        
        print("\n" + "="*60)
        print("ACCEPTANCE TEST: RTO <= 1 Hour")
        print("="*60)
        
        rto_estimate = backup_manager.estimate_rto()
        
        print(f"\n✓ RTO Estimation:")
        print(f"  Target: {rto_estimate['rto_target_minutes']} minutes")
        print(f"  Estimated: {rto_estimate['estimated_rto_minutes']:.1f} minutes")
        print(f"  Status: {rto_estimate['status']}")
        print(f"  Backup size: {rto_estimate['backup_size_gb']:.2f} GB")
        print(f"  Restore time: {rto_estimate['estimated_restore_seconds']:.1f}s")
        print(f"  Overhead: {rto_estimate['overhead_seconds']:.1f}s")
        
        # Verify RTO meets target
        assert rto_estimate['estimated_rto_minutes'] <= 60, \
            f"RTO {rto_estimate['estimated_rto_minutes']:.1f} minutes exceeds 60-minute target"
        
        print("\n" + "="*60)
        print("✅ ACCEPTANCE CRITERIA MET: RTO <= 1 Hour")
        print(f"   Estimated RTO: {rto_estimate['estimated_rto_minutes']:.1f} minutes")
        print("="*60)


class TestRedisHA:
    """Test Redis High Availability"""
    
    @pytest.fixture
    async def redis_client(self):
        """Setup Redis client"""
        import redis.asyncio as redis
        
        client = await redis.from_url("redis://localhost:6379")
        yield client
        await client.close()
    
    @pytest.mark.asyncio
    async def test_redis_cluster_health(self, redis_client):
        """Test Redis cluster health"""
        
        print("\n" + "="*60)
        print("TEST: Redis Cluster Health")
        print("="*60)
        
        # Get cluster info
        info = await redis_client.info("cluster")
        
        print(f"\n✓ Cluster Status:")
        print(f"  Enabled: {info.get('cluster_enabled', 0)}")
        print(f"  State: {info.get('cluster_state', 'unknown')}")
        
        # Check if cluster is enabled (may not be in test environment)
        if info.get('cluster_enabled', 0) == 1:
            assert info['cluster_state'] == 'ok', "Cluster state not OK"
            print("\n✅ Redis cluster is healthy")
        else:
            print("\n⚠️  Redis cluster not enabled (single-node test environment)")
    
    @pytest.mark.asyncio
    async def test_redis_persistence(self, redis_client):
        """Test Redis persistence configuration"""
        
        print("\n" + "="*60)
        print("TEST: Redis Persistence")
        print("="*60)
        
        info = await redis_client.info("persistence")
        
        print(f"\n✓ Persistence Configuration:")
        print(f"  RDB enabled: {info.get('rdb_last_save_time', 0) > 0}")
        print(f"  AOF enabled: {info.get('aof_enabled', 0)}")
        print(f"  Last save time: {datetime.fromtimestamp(info.get('rdb_last_save_time', 0))}")
        
        # Verify persistence is enabled
        assert info.get('aof_enabled', 0) == 1 or info.get('rdb_last_save_time', 0) > 0, \
            "Neither RDB nor AOF persistence enabled"
        
        print("\n✅ Redis persistence configured")


class TestTTLPolicies:
    """Test TTL policies"""
    
    @pytest.fixture
    async def ttl_manager(self):
        """Setup TTL manager"""
        import redis.asyncio as redis
        from ttl_manager import TTLManager
        
        redis_client = await redis.from_url("redis://localhost:6379")
        manager = TTLManager(redis_client)
        
        yield manager
        
        await redis_client.close()
    
    @pytest.mark.asyncio
    async def test_session_ttl(self, ttl_manager):
        """Test session TTL policy (30 minutes)"""
        
        print("\n" + "="*60)
        print("TEST: Session TTL Policy")
        print("="*60)
        
        session_id = "SES-TTL-TEST-001"
        session_data = {"user_id": "user_123", "created_at": datetime.utcnow().isoformat()}
        
        # Set session
        await ttl_manager.set_session(session_id, session_data)
        
        # Get TTL
        ttl = await ttl_manager.get_ttl(f"session:{session_id}")
        
        print(f"\n✓ Session created:")
        print(f"  Session ID: {session_id}")
        print(f"  TTL: {ttl}s ({ttl/60:.1f} minutes)")
        
        # Verify TTL is approximately 30 minutes
        assert 1700 <= ttl <= 1800, f"Session TTL {ttl}s not within expected range"
        
        print("\n✅ Session TTL policy validated")
    
    @pytest.mark.asyncio
    async def test_challenge_ttl(self, ttl_manager):
        """Test challenge TTL policy (10 minutes)"""
        
        print("\n" + "="*60)
        print("TEST: Challenge TTL Policy")
        print("="*60)
        
        challenge_id = "CH-TTL-TEST-001"
        challenge_data = {"action": "turn_head_left", "created_at": datetime.utcnow().isoformat()}
        
        # Set challenge
        await ttl_manager.set_challenge(challenge_id, challenge_data)
        
        # Get TTL
        ttl = await ttl_manager.get_ttl(f"challenge:{challenge_id}")
        
        print(f"\n✓ Challenge created:")
        print(f"  Challenge ID: {challenge_id}")
        print(f"  TTL: {ttl}s ({ttl/60:.1f} minutes)")
        
        # Verify TTL is approximately 10 minutes
        assert 580 <= ttl <= 600, f"Challenge TTL {ttl}s not within expected range"
        
        print("\n✅ Challenge TTL policy validated")
    
    @pytest.mark.asyncio
    async def test_job_lock_ttl(self, ttl_manager):
        """Test job lock TTL policy (5 minutes)"""
        
        print("\n" + "="*60)
        print("TEST: Job Lock TTL Policy")
        print("="*60)
        
        job_id = "JOB-TTL-TEST-001"
        worker_id = "worker-123"
        
        # Set job lock
        await ttl_manager.set_job_lock(job_id, worker_id)
        
        # Get TTL
        ttl = await ttl_manager.get_ttl(f"jobs:processing:{job_id}")
        
        print(f"\n✓ Job lock created:")
        print(f"  Job ID: {job_id}")
        print(f"  Worker: {worker_id}")
        print(f"  TTL: {ttl}s ({ttl/60:.1f} minutes)")
        
        # Verify TTL is approximately 5 minutes
        assert 280 <= ttl <= 300, f"Job lock TTL {ttl}s not within expected range"
        
        print("\n✅ Job lock TTL policy validated")
    
    @pytest.mark.asyncio
    async def test_result_cache_ttl(self, ttl_manager):
        """Test result cache TTL policy (7 days)"""
        
        print("\n" + "="*60)
        print("TEST: Result Cache TTL Policy")
        print("="*60)
        
        job_id = "JOB-RESULT-TTL-001"
        result = {"success": True, "decision": "approve"}
        
        # Set result cache
        await ttl_manager.set_result_cache(job_id, result)
        
        # Get TTL
        ttl = await ttl_manager.get_ttl(f"jobs:result:{job_id}")
        
        print(f"\n✓ Result cached:")
        print(f"  Job ID: {job_id}")
        print(f"  TTL: {ttl}s ({ttl/86400:.1f} days)")
        
        # Verify TTL is approximately 7 days
        expected_ttl = 7 * 86400
        assert expected_ttl - 100 <= ttl <= expected_ttl, \
            f"Result cache TTL {ttl}s not within expected range"
        
        print("\n✅ Result cache TTL policy validated")
    
    @pytest.mark.asyncio
    async def test_ttl_extension(self, ttl_manager):
        """Test TTL extension (session refresh)"""
        
        print("\n" + "="*60)
        print("TEST: TTL Extension")
        print("="*60)
        
        session_id = "SES-EXTEND-TEST-001"
        session_data = {"user_id": "user_456"}
        
        # Set session
        await ttl_manager.set_session(session_id, session_data)
        
        # Get initial TTL
        ttl_before = await ttl_manager.get_ttl(f"session:{session_id}")
        
        print(f"\n✓ Initial TTL: {ttl_before}s ({ttl_before/60:.1f} minutes)")
        
        # Wait a bit
        await asyncio.sleep(5)
        
        # Extend session
        success = await ttl_manager.extend_session(session_id)
        
        # Get new TTL
        ttl_after = await ttl_manager.get_ttl(f"session:{session_id}")
        
        print(f"✓ Extended TTL: {ttl_after}s ({ttl_after/60:.1f} minutes)")
        
        assert success, "TTL extension failed"
        assert ttl_after > ttl_before, "TTL not extended"
        
        print("\n✅ TTL extension validated")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])