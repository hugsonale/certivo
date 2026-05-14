"""
Performance Instrumentation
Automatic latency tracking and SLO recording
"""

import time
from typing import Optional, Callable, Any
from functools import wraps
from datetime import datetime
import asyncio
import logging

from slo_monitor import SLOMonitor, SLOMetric

logger = logging.getLogger(__name__)


class PerformanceTimer:
    """Context manager for timing operations"""
    
    def __init__(self, operation_name: str):
        self.operation_name = operation_name
        self.start_time = None
        self.end_time = None
        self.duration_ms = None
    
    def __enter__(self):
        self.start_time = time.perf_counter()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.end_time = time.perf_counter()
        self.duration_ms = (self.end_time - self.start_time) * 1000
        
        logger.debug(f"⏱️  {self.operation_name}: {self.duration_ms:.2f}ms")
        
        return False


class PerformanceInstrumentation:
    """
    Performance instrumentation helpers
    
    Features:
    - Automatic latency tracking
    - SLO metric recording
    - Function decorators
    - Request middleware
    """
    
    def __init__(self, slo_monitor: SLOMonitor):
        self.slo_monitor = slo_monitor
    
    def track_api_request(
        self,
        endpoint: str
    ):
        """
        Decorator to track API request latency and availability
        
        Usage:
            @instrumentation.track_api_request("/api/v1/challenges")
            async def create_challenge(...):
                ...
        """
        
        def decorator(func: Callable) -> Callable:
            @wraps(func)
            async def wrapper(*args, **kwargs):
                start_time = time.perf_counter()
                status_code = 500  # Default to error
                
                try:
                    result = await func(*args, **kwargs)
                    
                    # Extract status code from result
                    if isinstance(result, dict) and "status_code" in result:
                        status_code = result["status_code"]
                    elif hasattr(result, "status_code"):
                        status_code = result.status_code
                    else:
                        status_code = 200  # Assume success
                    
                    return result
                    
                except Exception as e:
                    logger.error(f"Error in {endpoint}: {e}")
                    status_code = 500
                    raise
                    
                finally:
                    end_time = time.perf_counter()
                    duration_ms = (end_time - start_time) * 1000
                    
                    # Record to SLO monitor
                    await self.slo_monitor.record_request(
                        endpoint=endpoint,
                        status_code=status_code,
                        duration_ms=duration_ms
                    )
            
            return wrapper
        return decorator
    
    def track_challenge_issuance(self):
        """
        Decorator to track challenge issuance latency
        
        Usage:
            @instrumentation.track_challenge_issuance()
            async def generate_challenge(...):
                ...
        """
        
        def decorator(func: Callable) -> Callable:
            @wraps(func)
            async def wrapper(*args, **kwargs):
                start_time = time.perf_counter()
                success = False
                challenge_id = None
                
                try:
                    result = await func(*args, **kwargs)
                    success = True
                    
                    # Extract challenge_id from result
                    if isinstance(result, dict):
                        challenge_id = result.get("challenge_id")
                    elif hasattr(result, "challenge_id"):
                        challenge_id = result.challenge_id
                    
                    return result
                    
                except Exception as e:
                    logger.error(f"Challenge issuance failed: {e}")
                    raise
                    
                finally:
                    end_time = time.perf_counter()
                    duration_ms = (end_time - start_time) * 1000
                    
                    if challenge_id:
                        await self.slo_monitor.record_challenge_issuance(
                            challenge_id=challenge_id,
                            duration_ms=duration_ms,
                            success=success
                        )
            
            return wrapper
        return decorator
    
    def track_verify_accept(self):
        """
        Decorator to track verification accept latency
        
        Usage:
            @instrumentation.track_verify_accept()
            async def verify_challenge(...):
                ...
        """
        
        def decorator(func: Callable) -> Callable:
            @wraps(func)
            async def wrapper(*args, **kwargs):
                start_time = time.perf_counter()
                success = False
                session_id = None
                upload_duration_ms = 0.0
                
                try:
                    result = await func(*args, **kwargs)
                    success = True
                    
                    # Extract metadata from result
                    if isinstance(result, dict):
                        session_id = result.get("session_id")
                        upload_duration_ms = result.get("upload_duration_ms", 0.0)
                    
                    return result
                    
                except Exception as e:
                    logger.error(f"Verification failed: {e}")
                    raise
                    
                finally:
                    end_time = time.perf_counter()
                    total_duration_ms = (end_time - start_time) * 1000
                    processing_duration_ms = total_duration_ms - upload_duration_ms
                    
                    if session_id:
                        await self.slo_monitor.record_verify_accept(
                            session_id=session_id,
                            duration_ms=total_duration_ms,
                            upload_duration_ms=upload_duration_ms,
                            processing_duration_ms=processing_duration_ms,
                            success=success
                        )
            
            return wrapper
        return decorator
    
    async def track_queue_job(
        self,
        job_id: str,
        queue_name: str,
        queued_at: datetime,
        job_func: Callable,
        *args,
        **kwargs
    ) -> Any:
        """
        Track queue job processing delay
        
        Args:
            job_id: Job identifier
            queue_name: Queue name
            queued_at: When job was queued
            job_func: Function to execute
            *args, **kwargs: Function arguments
        
        Returns:
            Job result
        """
        
        started_at = datetime.utcnow()
        
        try:
            result = await job_func(*args, **kwargs)
            return result
            
        finally:
            completed_at = datetime.utcnow()
            
            await self.slo_monitor.record_queue_processing(
                job_id=job_id,
                queued_at=queued_at,
                started_at=started_at,
                completed_at=completed_at,
                queue_name=queue_name
            )


class FastAPIMiddleware:
    """
    FastAPI middleware for automatic performance tracking
    
    Usage:
        from fastapi import FastAPI
        
        app = FastAPI()
        app.add_middleware(
            FastAPIMiddleware,
            slo_monitor=slo_monitor
        )
    """
    
    def __init__(self, app, slo_monitor: SLOMonitor):
        self.app = app
        self.slo_monitor = slo_monitor
    
    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        
        start_time = time.perf_counter()
        endpoint = scope["path"]
        status_code = 500
        
        async def send_wrapper(message):
            nonlocal status_code
            
            if message["type"] == "http.response.start":
                status_code = message["status"]
            
            await send(message)
        
        try:
            await self.app(scope, receive, send_wrapper)
            
        finally:
            end_time = time.perf_counter()
            duration_ms = (end_time - start_time) * 1000
            
            # Record metrics
            await self.slo_monitor.record_request(
                endpoint=endpoint,
                status_code=status_code,
                duration_ms=duration_ms
            )