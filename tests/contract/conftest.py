"""
Pytest configuration for contract tests
"""

import pytest
import yaml
import httpx
from typing import Dict, Any


@pytest.fixture(scope="session")
def openapi_spec() -> Dict[str, Any]:
    """Load OpenAPI specification"""
    with open("api/openapi.yaml", "r") as f:
        return yaml.safe_load(f)


@pytest.fixture(scope="session")
def base_url() -> str:
    """API base URL"""
    return "http://localhost:8000"


@pytest.fixture
async def async_client(base_url):
    """Async HTTP client"""
    async with httpx.AsyncClient(base_url=base_url) as client:
        yield client