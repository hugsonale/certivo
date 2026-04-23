"""
Pytest configuration for red team tests
"""

import pytest
import subprocess
import time
import os


@pytest.fixture(scope="session", autouse=True)
def start_test_services():
    """Start services for red team testing"""
    
    env = os.environ.copy()
    env["REDIS_URL"] = "redis://localhost:6379"
    env["TARGET_SESSION_ENTROPY"] = "20.0"
    
    # Start Redis
    redis_proc = subprocess.Popen(
        ["redis-server", "--port", "6379"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    
    time.sleep(2)
    
    # Start challenge service
    challenge_proc = subprocess.Popen(
        ["python", "services/challenge-service/main.py"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    
    # Start API gateway
    gateway_proc = subprocess.Popen(
        ["python", "services/api-gateway/main.py"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    
    time.sleep(10)
    
    yield
    
    # Cleanup
    gateway_proc.terminate()
    challenge_proc.terminate()
    redis_proc.terminate()