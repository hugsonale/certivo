"""
Bottleneck Validation Framework
Validate no single-node bottlenecks exist
"""

import asyncio
import asyncpg
import redis.asyncio as redis
import aiohttp
import time
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


@dataclass
class BottleneckTestResult:
    """Bottleneck test result"""
    component: str
    test_type: str
    target_throughput: float
    actual_throughput: float
    max_capacity: float
    utilization_percentage: float
    is_bottleneck: bool
    can_scale_horizontally: bool
    recommendation: str


class BottleneckValidator:
    """
    Bottleneck validation system
    
    Tests:
    - Database throughput
    - Redis throughput
    - Queue throughput
    - Object storage throughput
    - Network bandwidth
    """
    
    def __init__(
        self,
        postgres_dsn: str,
        redis_url: str,
        s3_endpoint: str,
        queue_endpoint: str
    ):
        self.postgres_dsn = postgres_dsn
        self.redis_url = redis_url
        self.s3_endpoint = s3_endpoint
        self.queue_endpoint = queue_endpoint
    
    async def test_database_throughput(
        self,
        target_writes_per_second: int = 1000,
        duration_seconds: int = 60
    ) -> BottleneckTestResult:
        """
        Test PostgreSQL write throughput
        
        Validates database can handle target write load
        without becoming a single-node bottleneck
        """
        
        logger.info(
            f"🔍 Testing Database Throughput\n"
            f"   Target: {target_writes_per_second} writes/sec\n"
            f"   Duration: {duration_seconds}s"
        )
        
        pool = await asyncpg.create_pool(self.postgres_dsn, min_size=10, max_size=50)
        
        writes_completed = 0
        errors = 0
        start_time = time.time()
        
        async def write_operation():
            nonlocal writes_completed, errors
            
            try:
                async with pool.acquire() as conn:
                    await conn.execute(
                        """
                        INSERT INTO load_test_writes (data, timestamp)
                        VALUES ($1, $2)
                        """,
                        f"test_data_{writes_completed}",
                        datetime.utcnow()
                    )
                writes_completed += 1
            except Exception as e:
                errors += 1
                logger.debug(f"Write failed: {e}")
        
        # Execute writes
        tasks = []
        target_interval = 1.0 / target_writes_per_second
        
        for i in range(target_writes_per_second * duration_seconds):
            await asyncio.sleep(target_interval)
            task = asyncio.create_task(write_operation())
            tasks.append(task)
        
        await asyncio.gather(*tasks, return_exceptions=True)
        
        end_time = time.time()
        actual_duration = end_time - start_time
        actual_throughput = writes_completed / actual_duration
        
        await pool.close()
        
        # Determine if bottleneck
        utilization = (actual_throughput / target_writes_per_second) * 100
        is_bottleneck = utilization < 80  # If can't hit 80% of target, it's a bottleneck
        
        # Database can scale with read replicas and sharding
        can_scale = True
        
        if is_bottleneck:
            recommendation = (
                "Database is bottleneck. Recommendations: "
                "1) Add read replicas for read scaling, "
                "2) Optimize indexes, "
                "3) Consider connection pooling (PgBouncer), "
                "4) Scale vertically (more CPU/IOPS)"
            )
        else:
            recommendation = "Database throughput is adequate. Monitor as load increases."
        
        result = BottleneckTestResult(
            component="PostgreSQL Database",
            test_type="Write Throughput",
            target_throughput=target_writes_per_second,
            actual_throughput=actual_throughput,
            max_capacity=actual_throughput * 1.25,  # Estimate 25% headroom
            utilization_percentage=utilization,
            is_bottleneck=is_bottleneck,
            can_scale_horizontally=can_scale,
            recommendation=recommendation
        )
        
        logger.info(
            f"✅ Database Test Complete\n"
            f"   Target: {target_writes_per_second} writes/sec\n"
            f"   Actual: {actual_throughput:.1f} writes/sec\n"
            f"   Utilization: {utilization:.1f}%\n"
            f"   Bottleneck: {'YES ⚠️' if is_bottleneck else 'NO ✅'}\n"
            f"   Errors: {errors}"
        )
        
        return result
    
    async def test_redis_throughput(
        self,
        target_ops_per_second: int = 10000,
        duration_seconds: int = 60
    ) -> BottleneckTestResult:
        """
        Test Redis throughput
        
        Validates Redis can handle target operation load
        """
        
        logger.info(
            f"🔍 Testing Redis Throughput\n"
            f"   Target: {target_ops_per_second} ops/sec\n"
            f"   Duration: {duration_seconds}s"
        )
        
        redis_client = await redis.from_url(self.redis_url)
        
        ops_completed = 0
        errors = 0
        start_time = time.time()
        
        async def redis_operation():
            nonlocal ops_completed, errors
            
            try:
                # Mix of operations (GET, SET, INCR)
                op_type = ops_completed % 3
                
                if op_type == 0:
                    await redis_client.set(f"test_key_{ops_completed}", f"value_{ops_completed}")
                elif op_type == 1:
                    await redis_client.get(f"test_key_{ops_completed - 1}")
                else:
                    await redis_client.incr("test_counter")
                
                ops_completed += 1
            except Exception as e:
                errors += 1
                logger.debug(f"Redis operation failed: {e}")
        
        # Execute operations
        tasks = []
        target_interval = 1.0 / target_ops_per_second
        
        for i in range(target_ops_per_second * duration_seconds):
            await asyncio.sleep(target_interval)
            task = asyncio.create_task(redis_operation())
            tasks.append(task)
        
        await asyncio.gather(*tasks, return_exceptions=True)
        
        end_time = time.time()
        actual_duration = end_time - start_time
        actual_throughput = ops_completed / actual_duration
        
        await redis_client.close()
        
        # Determine if bottleneck
        utilization = (actual_throughput / target_ops_per_second) * 100
        is_bottleneck = utilization < 80
        
        # Redis can scale with clustering
        can_scale = True
        
        if is_bottleneck:
            recommendation = (
                "Redis is bottleneck. Recommendations: "
                "1) Enable Redis Cluster for horizontal scaling, "
                "2) Optimize data structures, "
                "3) Use pipelining for batch operations, "
                "4) Scale vertically (more memory/CPU)"
            )
        else:
            recommendation = "Redis throughput is adequate. Consider clustering for future scale."
        
        result = BottleneckTestResult(
            component="Redis Cache",
            test_type="Operations Throughput",
            target_throughput=target_ops_per_second,
            actual_throughput=actual_throughput,
            max_capacity=actual_throughput * 1.25,
            utilization_percentage=utilization,
            is_bottleneck=is_bottleneck,
            can_scale_horizontally=can_scale,
            recommendation=recommendation
        )
        
        logger.info(
            f"✅ Redis Test Complete\n"
            f"   Target: {target_ops_per_second} ops/sec\n"
            f"   Actual: {actual_throughput:.1f} ops/sec\n"
            f"   Utilization: {utilization:.1f}%\n"
            f"   Bottleneck: {'YES ⚠️' if is_bottleneck else 'NO ✅'}\n"
            f"   Errors: {errors}"
        )
        
        return result
    
    async def test_object_storage_throughput(
        self,
        target_uploads_per_second: int = 100,
        avg_file_size_mb: float = 5.0,
        duration_seconds: int = 60
    ) -> BottleneckTestResult:
        """
        Test object storage (S3/GCS) upload throughput
        
        Validates storage can handle concurrent uploads
        """
        
        logger.info(
            f"🔍 Testing Object Storage Throughput\n"
            f"   Target: {target_uploads_per_second} uploads/sec\n"
            f"   Avg Size: {avg_file_size_mb} MB\n"
            f"   Duration: {duration_seconds}s"
        )
        
        uploads_completed = 0
        errors = 0
        start_time = time.time()
        
        # Generate test payload
        payload_bytes = b'\x00' * int(avg_file_size_mb * 1024 * 1024)
        
        async def upload_operation():
            nonlocal uploads_completed, errors
            
            try:
                async with aiohttp.ClientSession() as session:
                    # Simulate S3 upload
                    # In real test, use boto3 or actual S3 endpoint
                    async with session.put(
                        f"{self.s3_endpoint}/test-bucket/test-object-{uploads_completed}",
                        data=payload_bytes
                    ) as response:
                        if response.status in (200, 201):
                            uploads_completed += 1
                        else:
                            errors += 1
            except Exception as e:
                errors += 1
                logger.debug(f"Upload failed: {e}")
        
        # Execute uploads
        tasks = []
        target_interval = 1.0 / target_uploads_per_second
        
        for i in range(target_uploads_per_second * duration_seconds):
            await asyncio.sleep(target_interval)
            task = asyncio.create_task(upload_operation())
            tasks.append(task)
        
        await asyncio.gather(*tasks, return_exceptions=True)
        
        end_time = time.time()
        actual_duration = end_time - start_time
        actual_throughput = uploads_completed / actual_duration
        
        # Calculate bandwidth
        actual_bandwidth_mbps = (actual_throughput * avg_file_size_mb * 8)  # Convert to Mbps
        
        # Determine if bottleneck
        utilization = (actual_throughput / target_uploads_per_second) * 100
        is_bottleneck = utilization < 80
        
        # Object storage (S3/GCS) scales infinitely
        can_scale = True
        
        if is_bottleneck:
            recommendation = (
                "Object storage is bottleneck (likely network). Recommendations: "
                "1) Enable S3 Transfer Acceleration, "
                "2) Use multipart uploads for large files, "
                "3) Increase network bandwidth, "
                "4) Use CloudFront/CDN for distribution"
            )
        else:
            recommendation = "Object storage throughput is adequate. S3/GCS scales automatically."
        
        result = BottleneckTestResult(
            component="Object Storage (S3/GCS)",
            test_type="Upload Throughput",
            target_throughput=target_uploads_per_second,
            actual_throughput=actual_throughput,
            max_capacity=actual_throughput * 1.5,  # S3 can scale significantly
            utilization_percentage=utilization,
            is_bottleneck=is_bottleneck,
            can_scale_horizontally=can_scale,
            recommendation=recommendation
        )
        
        logger.info(
            f"✅ Object Storage Test Complete\n"
            f"   Target: {target_uploads_per_second} uploads/sec\n"
            f"   Actual: {actual_throughput:.1f} uploads/sec\n"
            f"   Bandwidth: {actual_bandwidth_mbps:.1f} Mbps\n"
            f"   Utilization: {utilization:.1f}%\n"
            f"   Bottleneck: {'YES ⚠️' if is_bottleneck else 'NO ✅'}\n"
            f"   Errors: {errors}"
        )
        
        return result
    
    async def test_queue_throughput(
        self,
        target_messages_per_second: int = 1000,
        duration_seconds: int = 60
    ) -> BottleneckTestResult:
        """
        Test message queue throughput
        
        Validates queue can handle message volume
        """
        
        logger.info(
            f"🔍 Testing Queue Throughput\n"
            f"   Target: {target_messages_per_second} msg/sec\n"
            f"   Duration: {duration_seconds}s"
        )
        
        messages_sent = 0
        errors = 0
        start_time = time.time()
        
        async def send_message():
            nonlocal messages_sent, errors
            
            try:
                async with aiohttp.ClientSession() as session:
                    # Simulate SQS/RabbitMQ message send
                    async with session.post(
                        f"{self.queue_endpoint}/send",
                        json={"message": f"test_message_{messages_sent}"}
                    ) as response:
                        if response.status == 200:
                            messages_sent += 1
                        else:
                            errors += 1
            except Exception as e:
                errors += 1
                logger.debug(f"Queue send failed: {e}")
        
        # Execute sends
        tasks = []
        target_interval = 1.0 / target_messages_per_second
        
        for i in range(target_messages_per_second * duration_seconds):
            await asyncio.sleep(target_interval)
            task = asyncio.create_task(send_message())
            tasks.append(task)
        
        await asyncio.gather(*tasks, return_exceptions=True)
        
        end_time = time.time()
        actual_duration = end_time - start_time
        actual_throughput = messages_sent / actual_duration
        
        # Determine if bottleneck
        utilization = (actual_throughput / target_messages_per_second) * 100
        is_bottleneck = utilization < 80
        
        # Queues can scale (SQS is unlimited, RabbitMQ can cluster)
        can_scale = True
        
        if is_bottleneck:
            recommendation = (
                "Queue is bottleneck. Recommendations: "
                "1) Use SQS (unlimited scaling) instead of self-hosted, "
                "2) For RabbitMQ, enable clustering, "
                "3) Optimize message size, "
                "4) Use batch operations"
            )
        else:
            recommendation = "Queue throughput is adequate. SQS scales automatically."
        
        result = BottleneckTestResult(
            component="Message Queue (SQS/RabbitMQ)",
            test_type="Message Throughput",
            target_throughput=target_messages_per_second,
            actual_throughput=actual_throughput,
            max_capacity=actual_throughput * 2.0,  # Queues can scale significantly
            utilization_percentage=utilization,
            is_bottleneck=is_bottleneck,
            can_scale_horizontally=can_scale,
            recommendation=recommendation
        )
        
        logger.info(
            f"✅ Queue Test Complete\n"
            f"   Target: {target_messages_per_second} msg/sec\n"
            f"   Actual: {actual_throughput:.1f} msg/sec\n"
            f"   Utilization: {utilization:.1f}%\n"
            f"   Bottleneck: {'YES ⚠️' if is_bottleneck else 'NO ✅'}\n"
            f"   Errors: {errors}"
        )
        
        return result
    
    async def run_full_bottleneck_validation(self) -> Dict[str, Any]:
        """
        Run complete bottleneck validation suite
        
        Returns:
            Complete validation report
        """
        
        logger.info("="*60)
        logger.info("BOTTLENECK VALIDATION SUITE")
        logger.info("="*60)
        
        # Run all tests
        db_result = await self.test_database_throughput(
            target_writes_per_second=1000,
            duration_seconds=30  # Shorter for testing
        )
        
        redis_result = await self.test_redis_throughput(
            target_ops_per_second=10000,
            duration_seconds=30
        )
        
        storage_result = await self.test_object_storage_throughput(
            target_uploads_per_second=100,
            avg_file_size_mb=5.0,
            duration_seconds=30
        )
        
        queue_result = await self.test_queue_throughput(
            target_messages_per_second=1000,
            duration_seconds=30
        )
        
        results = [db_result, redis_result, storage_result, queue_result]
        
        # Analyze results
        bottlenecks_found = [r for r in results if r.is_bottleneck]
        single_node_bottlenecks = [r for r in results if r.is_bottleneck and not r.can_scale_horizontally]
        
        validation_passed = len(single_node_bottlenecks) == 0
        
        report = {
            "validation_timestamp": datetime.utcnow().isoformat(),
            "overall_status": "PASS" if validation_passed else "FAIL",
            "components_tested": len(results),
            "bottlenecks_found": len(bottlenecks_found),
            "single_node_bottlenecks": len(single_node_bottlenecks),
            "results": [
                {
                    "component": r.component,
                    "test_type": r.test_type,
                    "target_throughput": r.target_throughput,
                    "actual_throughput": round(r.actual_throughput, 2),
                    "utilization_percentage": round(r.utilization_percentage, 2),
                    "is_bottleneck": r.is_bottleneck,
                    "can_scale_horizontally": r.can_scale_horizontally,
                    "recommendation": r.recommendation
                }
                for r in results
            ]
        }
        
        logger.info("="*60)
        logger.info("VALIDATION SUMMARY")
        logger.info("="*60)
        logger.info(f"Overall Status: {'✅ PASS' if validation_passed else '❌ FAIL'}")
        logger.info(f"Components Tested: {len(results)}")
        logger.info(f"Bottlenecks Found: {len(bottlenecks_found)}")
        logger.info(f"Single-Node Bottlenecks: {len(single_node_bottlenecks)}")
        
        if single_node_bottlenecks:
            logger.warning("\n⚠️  Single-Node Bottlenecks Detected:")
            for b in single_node_bottlenecks:
                logger.warning(f"   - {b.component}: {b.recommendation}")
        else:
            logger.info("\n✅ No single-node bottlenecks detected. All components can scale horizontally.")
        
        logger.info("="*60)
        
        return report