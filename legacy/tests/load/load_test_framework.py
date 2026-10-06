"""
Load Testing Framework
Realistic load tests with video payload distributions
"""

import asyncio
import aiohttp
import time
import random
import statistics
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from datetime import datetime
import logging
import io

logger = logging.getLogger(__name__)


@dataclass
class LoadTestConfig:
    """Load test configuration"""
    target_rps: float
    duration_seconds: int
    ramp_up_seconds: int = 60
    video_size_distribution: Dict[str, float] = field(default_factory=lambda: {
        "p10": 2.5,   # MB
        "p50": 5.0,
        "p90": 8.0,
        "p99": 12.0
    })
    
    def get_video_size_mb(self) -> float:
        """Sample video size from distribution"""
        rand = random.random()
        
        if rand < 0.10:
            return self.video_size_distribution["p10"]
        elif rand < 0.50:
            return self.video_size_distribution["p50"]
        elif rand < 0.90:
            return self.video_size_distribution["p90"]
        else:
            return self.video_size_distribution["p99"]


@dataclass
class LoadTestResult:
    """Load test result"""
    total_requests: int
    successful_requests: int
    failed_requests: int
    
    latencies_ms: List[float] = field(default_factory=list)
    
    start_time: datetime = field(default_factory=datetime.utcnow)
    end_time: Optional[datetime] = None
    
    @property
    def success_rate(self) -> float:
        if self.total_requests == 0:
            return 0.0
        return (self.successful_requests / self.total_requests) * 100
    
    @property
    def p50_latency(self) -> float:
        if not self.latencies_ms:
            return 0.0
        return statistics.median(self.latencies_ms)
    
    @property
    def p95_latency(self) -> float:
        if not self.latencies_ms:
            return 0.0
        return statistics.quantiles(self.latencies_ms, n=100)[94]
    
    @property
    def p99_latency(self) -> float:
        if not self.latencies_ms:
            return 0.0
        return statistics.quantiles(self.latencies_ms, n=100)[98]
    
    @property
    def max_latency(self) -> float:
        if not self.latencies_ms:
            return 0.0
        return max(self.latencies_ms)
    
    @property
    def actual_rps(self) -> float:
        if not self.end_time:
            return 0.0
        duration = (self.end_time - self.start_time).total_seconds()
        if duration == 0:
            return 0.0
        return self.total_requests / duration
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_requests": self.total_requests,
            "successful_requests": self.successful_requests,
            "failed_requests": self.failed_requests,
            "success_rate": round(self.success_rate, 2),
            "actual_rps": round(self.actual_rps, 2),
            "latency_p50_ms": round(self.p50_latency, 1),
            "latency_p95_ms": round(self.p95_latency, 1),
            "latency_p99_ms": round(self.p99_latency, 1),
            "latency_max_ms": round(self.max_latency, 1),
            "duration_seconds": (self.end_time - self.start_time).total_seconds() if self.end_time else 0
        }


class LoadTester:
    """
    Load testing framework
    
    Features:
    - Realistic video payload generation
    - Distributed load generation
    - Ramp-up and steady-state testing
    - Real-time metrics collection
    """
    
    def __init__(
        self,
        api_base_url: str,
        config: LoadTestConfig
    ):
        self.api_base_url = api_base_url
        self.config = config
        
        self.result = LoadTestResult(
            total_requests=0,
            successful_requests=0,
            failed_requests=0
        )
    
    def _generate_video_payload(self, size_mb: float) -> bytes:
        """Generate realistic video payload"""
        
        # Generate random bytes to simulate video
        # In real testing, use actual video files
        size_bytes = int(size_mb * 1024 * 1024)
        
        # For testing, just return random bytes
        # In production, load actual video file
        return b'\x00' * size_bytes
    
    async def _execute_challenge_issuance(
        self,
        session: aiohttp.ClientSession
    ) -> Optional[Dict[str, Any]]:
        """Execute challenge issuance request"""
        
        start_time = time.perf_counter()
        
        try:
            async with session.post(
                f"{self.api_base_url}/api/v1/challenges",
                json={"device_id": f"load-test-device-{random.randint(1, 10000)}"}
            ) as response:
                end_time = time.perf_counter()
                duration_ms = (end_time - start_time) * 1000
                
                if response.status == 200:
                    data = await response.json()
                    return {
                        "success": True,
                        "duration_ms": duration_ms,
                        "challenge_id": data.get("challenge_id")
                    }
                else:
                    return {
                        "success": False,
                        "duration_ms": duration_ms,
                        "status_code": response.status
                    }
                    
        except Exception as e:
            end_time = time.perf_counter()
            duration_ms = (end_time - start_time) * 1000
            
            logger.error(f"Challenge issuance failed: {e}")
            
            return {
                "success": False,
                "duration_ms": duration_ms,
                "error": str(e)
            }
    
    async def _execute_verification(
        self,
        session: aiohttp.ClientSession,
        challenge_id: str
    ) -> Dict[str, Any]:
        """Execute verification request with video upload"""
        
        start_time = time.perf_counter()
        
        # Sample video size from distribution
        video_size_mb = self.config.get_video_size_mb()
        video_payload = self._generate_video_payload(video_size_mb)
        
        try:
            # Create multipart form data
            data = aiohttp.FormData()
            data.add_field('challenge_id', challenge_id)
            data.add_field(
                'video',
                video_payload,
                filename='verification.mp4',
                content_type='video/mp4'
            )
            
            async with session.post(
                f"{self.api_base_url}/api/v1/verify",
                data=data
            ) as response:
                end_time = time.perf_counter()
                duration_ms = (end_time - start_time) * 1000
                
                if response.status == 200:
                    return {
                        "success": True,
                        "duration_ms": duration_ms,
                        "video_size_mb": video_size_mb
                    }
                else:
                    return {
                        "success": False,
                        "duration_ms": duration_ms,
                        "status_code": response.status,
                        "video_size_mb": video_size_mb
                    }
                    
        except Exception as e:
            end_time = time.perf_counter()
            duration_ms = (end_time - start_time) * 1000
            
            logger.error(f"Verification failed: {e}")
            
            return {
                "success": False,
                "duration_ms": duration_ms,
                "error": str(e),
                "video_size_mb": video_size_mb
            }
    
    async def _execute_full_verification_flow(
        self,
        session: aiohttp.ClientSession
    ):
        """Execute complete verification flow (challenge + verify)"""
        
        # Step 1: Get challenge
        challenge_result = await self._execute_challenge_issuance(session)
        
        if not challenge_result or not challenge_result["success"]:
            self.result.failed_requests += 1
            self.result.total_requests += 1
            return
        
        # Step 2: Verify challenge
        verify_result = await self._execute_verification(
            session,
            challenge_result["challenge_id"]
        )
        
        # Record results
        self.result.total_requests += 1
        
        if verify_result["success"]:
            self.result.successful_requests += 1
            total_duration = challenge_result["duration_ms"] + verify_result["duration_ms"]
            self.result.latencies_ms.append(total_duration)
        else:
            self.result.failed_requests += 1
    
    async def run_load_test(self) -> LoadTestResult:
        """
        Run complete load test
        
        Returns:
            Load test results
        """
        
        logger.info(
            f"🚀 Starting Load Test\n"
            f"   Target: {self.config.target_rps} req/sec\n"
            f"   Duration: {self.config.duration_seconds}s\n"
            f"   Ramp-up: {self.config.ramp_up_seconds}s"
        )
        
        self.result.start_time = datetime.utcnow()
        
        # Create aiohttp session
        timeout = aiohttp.ClientTimeout(total=300)  # 5 minute timeout
        connector = aiohttp.TCPConnector(limit=1000)  # Max 1000 concurrent connections
        
        async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
            # Calculate request intervals
            total_duration = self.config.ramp_up_seconds + self.config.duration_seconds
            total_requests = int(self.config.target_rps * self.config.duration_seconds)
            
            tasks = []
            
            for i in range(total_requests):
                # Calculate when this request should start
                progress = i / total_requests
                
                if progress < (self.config.ramp_up_seconds / total_duration):
                    # Ramp-up phase: gradually increase RPS
                    ramp_progress = progress / (self.config.ramp_up_seconds / total_duration)
                    current_rps = self.config.target_rps * ramp_progress
                else:
                    # Steady-state phase
                    current_rps = self.config.target_rps
                
                # Schedule request
                delay = i / self.config.target_rps
                
                await asyncio.sleep(delay - (time.time() - self.result.start_time.timestamp()) if i > 0 else 0)
                
                # Execute request
                task = asyncio.create_task(
                    self._execute_full_verification_flow(session)
                )
                tasks.append(task)
                
                # Report progress every 100 requests
                if (i + 1) % 100 == 0:
                    logger.info(
                        f"   Progress: {i + 1}/{total_requests} "
                        f"({(i + 1) / total_requests * 100:.1f}%)"
                    )
            
            # Wait for all tasks to complete
            await asyncio.gather(*tasks, return_exceptions=True)
        
        self.result.end_time = datetime.utcnow()
        
        logger.info(
            f"✅ Load Test Complete\n"
            f"   Total Requests: {self.result.total_requests}\n"
            f"   Successful: {self.result.successful_requests}\n"
            f"   Failed: {self.result.failed_requests}\n"
            f"   Success Rate: {self.result.success_rate:.2f}%\n"
            f"   Actual RPS: {self.result.actual_rps:.2f}\n"
            f"   P50 Latency: {self.result.p50_latency:.1f}ms\n"
            f"   P95 Latency: {self.result.p95_latency:.1f}ms\n"
            f"   P99 Latency: {self.result.p99_latency:.1f}ms"
        )
        
        return self.result