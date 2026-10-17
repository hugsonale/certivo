"""
Capacity Planning Framework
Calculate and validate system capacity at scale
"""

from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from enum import Enum
import math
import logging

logger = logging.getLogger(__name__)


class ScalingPhase(str, Enum):
    """Scaling phase definitions"""
    PHASE_1 = "phase_1"  # 10k/day
    PHASE_2 = "phase_2"  # 100k/day
    PHASE_3 = "phase_3"  # 1M/day


@dataclass
class CapacityTarget:
    """Capacity target definition"""
    phase: ScalingPhase
    daily_verifications: int
    peak_multiplier: float = 3.0  # Peak is 3x average
    
    @property
    def avg_verifications_per_second(self) -> float:
        """Average verifications per second"""
        return self.daily_verifications / 86400
    
    @property
    def peak_verifications_per_second(self) -> float:
        """Peak verifications per second"""
        return self.avg_verifications_per_second * self.peak_multiplier
    
    @property
    def avg_verifications_per_minute(self) -> float:
        """Average verifications per minute"""
        return self.avg_verifications_per_second * 60
    
    @property
    def peak_verifications_per_minute(self) -> float:
        """Peak verifications per minute"""
        return self.peak_verifications_per_second * 60


@dataclass
class VideoPayloadDistribution:
    """Realistic video payload size distribution"""
    
    # Video size distribution (percentiles)
    p10_mb: float = 2.5   # 10th percentile: 2.5 MB
    p50_mb: float = 5.0   # 50th percentile: 5.0 MB
    p90_mb: float = 8.0   # 90th percentile: 8.0 MB
    p99_mb: float = 12.0  # 99th percentile: 12.0 MB
    
    # Video duration distribution
    p10_seconds: float = 3.0
    p50_seconds: float = 5.0
    p90_seconds: float = 8.0
    p99_seconds: float = 12.0
    
    # Resolution distribution
    resolution_480p_pct: float = 0.10  # 10% 480p
    resolution_720p_pct: float = 0.50  # 50% 720p
    resolution_1080p_pct: float = 0.35  # 35% 1080p
    resolution_4k_pct: float = 0.05     # 5% 4K
    
    def get_average_size_mb(self) -> float:
        """Calculate weighted average size"""
        # Approximate weighted average
        return (
            self.p10_mb * 0.10 +
            self.p50_mb * 0.40 +
            self.p90_mb * 0.40 +
            self.p99_mb * 0.10
        )
    
    def get_average_duration_seconds(self) -> float:
        """Calculate weighted average duration"""
        return (
            self.p10_seconds * 0.10 +
            self.p50_seconds * 0.40 +
            self.p90_seconds * 0.40 +
            self.p99_seconds * 0.10
        )


@dataclass
class ComponentCapacity:
    """Individual component capacity requirements"""
    component_name: str
    
    # Resource requirements per verification
    cpu_cores_per_verification: float
    memory_mb_per_verification: float
    disk_iops_per_verification: float
    network_mbps_per_verification: float
    
    # Processing time
    avg_processing_time_seconds: float
    
    # Scaling parameters
    instances_required: int
    cpu_per_instance: int
    memory_per_instance_gb: int
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "component": self.component_name,
            "instances_required": self.instances_required,
            "cpu_per_instance": self.cpu_per_instance,
            "memory_per_instance_gb": self.memory_per_instance_gb,
            "total_cpu_cores": self.instances_required * self.cpu_per_instance,
            "total_memory_gb": self.instances_required * self.memory_per_instance_gb,
            "avg_processing_time_seconds": self.avg_processing_time_seconds
        }


class CapacityPlanner:
    """
    Capacity planning and validation
    
    Features:
    - Calculate resource requirements for target load
    - Identify bottlenecks
    - Validate no single-node limits
    - Generate scaling recommendations
    """
    
    # Capacity targets
    PHASE_TARGETS = {
        ScalingPhase.PHASE_1: CapacityTarget(
            phase=ScalingPhase.PHASE_1,
            daily_verifications=10_000
        ),
        ScalingPhase.PHASE_2: CapacityTarget(
            phase=ScalingPhase.PHASE_2,
            daily_verifications=100_000
        ),
        ScalingPhase.PHASE_3: CapacityTarget(
            phase=ScalingPhase.PHASE_3,
            daily_verifications=1_000_000
        )
    }
    
    def __init__(self, video_distribution: Optional[VideoPayloadDistribution] = None):
        self.video_distribution = video_distribution or VideoPayloadDistribution()
    
    def calculate_api_gateway_capacity(
        self,
        target: CapacityTarget
    ) -> ComponentCapacity:
        """
        Calculate API gateway capacity requirements
        
        API Gateway handles:
        - Request routing
        - Authentication
        - Rate limiting
        - Response aggregation
        """
        
        peak_rps = target.peak_verifications_per_second
        
        # API gateway can handle ~500 req/sec per instance
        # With 50% headroom for bursts
        capacity_per_instance = 500
        instances_required = math.ceil(peak_rps / capacity_per_instance * 2)
        
        return ComponentCapacity(
            component_name="API Gateway",
            cpu_cores_per_verification=0.002,
            memory_mb_per_verification=5,
            disk_iops_per_verification=0,
            network_mbps_per_verification=0.1,
            avg_processing_time_seconds=0.010,
            instances_required=max(instances_required, 2),  # Min 2 for HA
            cpu_per_instance=2,
            memory_per_instance_gb=4
        )
    
    def calculate_challenge_service_capacity(
        self,
        target: CapacityTarget
    ) -> ComponentCapacity:
        """
        Calculate challenge service capacity
        
        Challenge service handles:
        - Template selection
        - Random value generation
        - Locale processing
        """
        
        peak_rps = target.peak_verifications_per_second
        
        # Challenge service can handle ~200 req/sec per instance
        capacity_per_instance = 200
        instances_required = math.ceil(peak_rps / capacity_per_instance * 2)
        
        return ComponentCapacity(
            component_name="Challenge Service",
            cpu_cores_per_verification=0.005,
            memory_mb_per_verification=10,
            disk_iops_per_verification=1,
            network_mbps_per_verification=0.05,
            avg_processing_time_seconds=0.100,
            instances_required=max(instances_required, 2),
            cpu_per_instance=4,
            memory_per_instance_gb=8
        )
    
    def calculate_verification_worker_capacity(
        self,
        target: CapacityTarget
    ) -> ComponentCapacity:
        """
        Calculate verification worker capacity
        
        Verification workers handle:
        - Video decode
        - Liveness detection (GPU)
        - Risk scoring
        - Policy evaluation
        """
        
        peak_rpm = target.peak_verifications_per_minute
        
        # Each worker can process ~1 verification per 1.5 seconds
        # = 40 verifications per minute per worker
        verifications_per_worker_per_minute = 40
        
        instances_required = math.ceil(
            peak_rpm / verifications_per_worker_per_minute * 1.5  # 50% headroom
        )
        
        return ComponentCapacity(
            component_name="Verification Worker",
            cpu_cores_per_verification=0.5,
            memory_mb_per_verification=512,
            disk_iops_per_verification=10,
            network_mbps_per_verification=5.0,
            avg_processing_time_seconds=1.5,
            instances_required=max(instances_required, 3),  # Min 3 for redundancy
            cpu_per_instance=8,
            memory_per_instance_gb=16
        )
    
    def calculate_database_capacity(
        self,
        target: CapacityTarget
    ) -> ComponentCapacity:
        """
        Calculate database capacity
        
        Database handles:
        - Session storage
        - Challenge metadata
        - Risk assessments
        - Explainability records
        """
        
        peak_rps = target.peak_verifications_per_second
        
        # Postgres can handle ~10,000 writes/sec with proper hardware
        # Each verification = ~5 writes
        writes_per_verification = 5
        total_writes_per_sec = peak_rps * writes_per_verification
        
        # Use read replicas for scale-out
        # Primary handles writes, replicas handle reads
        instances_required = math.ceil(total_writes_per_sec / 5000) + 2  # +2 replicas
        
        return ComponentCapacity(
            component_name="PostgreSQL Database",
            cpu_cores_per_verification=0.01,
            memory_mb_per_verification=2,
            disk_iops_per_verification=50,
            network_mbps_per_verification=0.5,
            avg_processing_time_seconds=0.020,
            instances_required=max(instances_required, 3),  # 1 primary + 2 replicas
            cpu_per_instance=16,
            memory_per_instance_gb=64
        )
    
    def calculate_redis_capacity(
        self,
        target: CapacityTarget
    ) -> ComponentCapacity:
        """
        Calculate Redis capacity
        
        Redis handles:
        - Session cache
        - Rate limiting
        - Queue management
        - Policy cache
        """
        
        peak_rps = target.peak_verifications_per_second
        
        # Redis can handle ~100,000 ops/sec per instance
        # Each verification = ~20 Redis operations
        ops_per_verification = 20
        total_ops_per_sec = peak_rps * ops_per_verification
        
        instances_required = math.ceil(total_ops_per_sec / 50000)  # 50k with headroom
        
        return ComponentCapacity(
            component_name="Redis Cache",
            cpu_cores_per_verification=0.0002,
            memory_mb_per_verification=1,
            disk_iops_per_verification=0,
            network_mbps_per_verification=0.1,
            avg_processing_time_seconds=0.002,
            instances_required=max(instances_required, 2),  # Min 2 for HA
            cpu_per_instance=4,
            memory_per_instance_gb=16
        )
    
    def calculate_object_storage_capacity(
        self,
        target: CapacityTarget
    ) -> ComponentCapacity:
        """
        Calculate object storage capacity
        
        Object storage handles:
        - Video uploads
        - Video archival
        - Challenge images
        """
        
        daily_verifications = target.daily_verifications
        avg_video_size_mb = self.video_distribution.get_average_size_mb()
        
        # Storage per day
        daily_storage_gb = (daily_verifications * avg_video_size_mb) / 1024
        
        # Keep videos for 90 days
        total_storage_gb = daily_storage_gb * 90
        
        # Peak upload bandwidth
        peak_rps = target.peak_verifications_per_second
        peak_bandwidth_mbps = peak_rps * avg_video_size_mb * 8  # Convert to Mbps
        
        # S3/GCS can handle unlimited throughput with proper configuration
        # No instance count - using managed service
        
        return ComponentCapacity(
            component_name="Object Storage (S3/GCS)",
            cpu_cores_per_verification=0,
            memory_mb_per_verification=0,
            disk_iops_per_verification=0,
            network_mbps_per_verification=avg_video_size_mb * 8,
            avg_processing_time_seconds=0.500,  # Upload time
            instances_required=1,  # Managed service
            cpu_per_instance=0,
            memory_per_instance_gb=0
        )
    
    def calculate_message_queue_capacity(
        self,
        target: CapacityTarget
    ) -> ComponentCapacity:
        """
        Calculate message queue capacity
        
        Message queue handles:
        - Async verification jobs
        - Analytics events
        - Notification dispatch
        """
        
        peak_rpm = target.peak_verifications_per_minute
        
        # RabbitMQ/SQS can handle ~10,000 msg/sec
        # Each verification = 3 messages (enqueue, process, complete)
        messages_per_verification = 3
        total_messages_per_minute = peak_rpm * messages_per_verification
        
        # Use managed service (SQS) or clustered RabbitMQ
        instances_required = math.ceil(total_messages_per_minute / 30000)
        
        return ComponentCapacity(
            component_name="Message Queue (SQS/RabbitMQ)",
            cpu_cores_per_verification=0.001,
            memory_mb_per_verification=0.5,
            disk_iops_per_verification=2,
            network_mbps_per_verification=0.05,
            avg_processing_time_seconds=0.010,
            instances_required=max(instances_required, 2),
            cpu_per_instance=4,
            memory_per_instance_gb=8
        )
    
    def generate_capacity_plan(
        self,
        phase: ScalingPhase
    ) -> Dict[str, Any]:
        """
        Generate complete capacity plan for target phase
        
        Args:
            phase: Target scaling phase
        
        Returns:
            Complete capacity plan
        """
        
        target = self.PHASE_TARGETS[phase]
        
        # Calculate capacity for each component
        api_gateway = self.calculate_api_gateway_capacity(target)
        challenge_service = self.calculate_challenge_service_capacity(target)
        verification_worker = self.calculate_verification_worker_capacity(target)
        database = self.calculate_database_capacity(target)
        redis = self.calculate_redis_capacity(target)
        object_storage = self.calculate_object_storage_capacity(target)
        message_queue = self.calculate_message_queue_capacity(target)
        
        components = [
            api_gateway,
            challenge_service,
            verification_worker,
            database,
            redis,
            object_storage,
            message_queue
        ]
        
        # Calculate totals
        total_instances = sum(c.instances_required for c in components if c.cpu_per_instance > 0)
        total_cpu_cores = sum(c.instances_required * c.cpu_per_instance for c in components)
        total_memory_gb = sum(c.instances_required * c.memory_per_instance_gb for c in components)
        
        # Calculate daily storage
        avg_video_size_mb = self.video_distribution.get_average_size_mb()
        daily_storage_gb = (target.daily_verifications * avg_video_size_mb) / 1024
        
        # Calculate costs (rough estimates)
        compute_cost_per_month = total_cpu_cores * 30  # $30/core/month
        storage_cost_per_month = daily_storage_gb * 90 * 0.023  # $0.023/GB/month S3
        
        plan = {
            "phase": phase.value,
            "target": {
                "daily_verifications": target.daily_verifications,
                "avg_verifications_per_second": round(target.avg_verifications_per_second, 2),
                "peak_verifications_per_second": round(target.peak_verifications_per_second, 2),
                "peak_multiplier": target.peak_multiplier
            },
            "video_distribution": {
                "avg_size_mb": round(avg_video_size_mb, 2),
                "avg_duration_seconds": round(self.video_distribution.get_average_duration_seconds(), 2),
                "p50_size_mb": self.video_distribution.p50_mb,
                "p90_size_mb": self.video_distribution.p90_mb,
                "p99_size_mb": self.video_distribution.p99_mb
            },
            "components": [c.to_dict() for c in components],
            "totals": {
                "total_instances": total_instances,
                "total_cpu_cores": total_cpu_cores,
                "total_memory_gb": total_memory_gb,
                "daily_storage_gb": round(daily_storage_gb, 2),
                "90_day_storage_gb": round(daily_storage_gb * 90, 2)
            },
            "costs_estimate": {
                "compute_per_month_usd": round(compute_cost_per_month, 2),
                "storage_per_month_usd": round(storage_cost_per_month, 2),
                "total_per_month_usd": round(compute_cost_per_month + storage_cost_per_month, 2)
            },
            "bottleneck_analysis": self._analyze_bottlenecks(components)
        }
        
        logger.info(
            f"📊 Capacity Plan Generated: {phase.value}\n"
            f"   Daily: {target.daily_verifications:,} verifications\n"
            f"   Peak: {target.peak_verifications_per_second:.1f} req/sec\n"
            f"   Instances: {total_instances}\n"
            f"   CPU Cores: {total_cpu_cores}\n"
            f"   Memory: {total_memory_gb} GB\n"
            f"   Storage (90d): {daily_storage_gb * 90:.1f} GB"
        )
        
        return plan
    
    def _analyze_bottlenecks(
        self,
        components: List[ComponentCapacity]
    ) -> Dict[str, Any]:
        """Analyze potential bottlenecks"""
        
        bottlenecks = []
        
        for component in components:
            # Check if component is single-instance
            if component.instances_required == 1 and component.cpu_per_instance > 0:
                bottlenecks.append({
                    "component": component.component_name,
                    "issue": "Single instance - no horizontal scaling",
                    "severity": "high",
                    "recommendation": "Configure clustering or managed service"
                })
            
            # Check for high resource usage per verification
            if component.cpu_cores_per_verification > 0.1:
                bottlenecks.append({
                    "component": component.component_name,
                    "issue": f"High CPU usage: {component.cpu_cores_per_verification} cores/verification",
                    "severity": "medium",
                    "recommendation": "Consider GPU acceleration or optimization"
                })
            
            if component.memory_mb_per_verification > 200:
                bottlenecks.append({
                    "component": component.component_name,
                    "issue": f"High memory usage: {component.memory_mb_per_verification} MB/verification",
                    "severity": "medium",
                    "recommendation": "Review memory usage and optimize"
                })
        
        return {
            "bottlenecks_found": len(bottlenecks),
            "bottlenecks": bottlenecks,
            "single_node_issues": len([b for b in bottlenecks if "Single instance" in b["issue"]])
        }