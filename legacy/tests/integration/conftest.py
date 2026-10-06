"""
Pytest configuration for integration tests
"""

import pytest
import asyncio
import subprocess
import time
import os


@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests"""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session", autouse=True)
def start_services():
    """Start all services before tests"""
    
    # Start Redis
    redis_proc = subprocess.Popen(
        ["redis-server", "--port", "6379"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    
    time.sleep(2)
    
    # Start API Gateway
    env = os.environ.copy()
    env["REDIS_URL"] = "redis://localhost:6379"
    
    gateway_proc = subprocess.Popen(
        ["python", "services/api-gateway/main.py"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    
    time.sleep(5)
    
    yield
    
    # Cleanup
    gateway_proc.terminate()
    redis_proc.terminate()