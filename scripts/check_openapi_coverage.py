#!/usr/bin/env python3
"""
Verify all public endpoints are documented in OpenAPI spec
"""

import yaml
import sys


def check_openapi_coverage():
    """Verify OpenAPI specification coverage"""
    
    with open("api/openapi.yaml", "r") as f:
        spec = yaml.safe_load(f)
    
    paths = spec.get("paths", {})
    
    # Required public endpoints
    required_endpoints = [
        "/v1/challenge",
        "/v1/verify",
        "/v1/finalize",
        "/v1/device/{device_id}/stats",
        "/admin/sessions",
        "/admin/device/{device_id}/revoke"
    ]
    
    missing = []
    for endpoint in required_endpoints:
        if endpoint not in paths:
            missing.append(endpoint)
    
    if missing:
        print("❌ Missing endpoints in OpenAPI spec:")
        for endpoint in missing:
            print(f"  - {endpoint}")
        sys.exit(1)
    
    # Verify all endpoints have required fields
    for path, methods in paths.items():
        for method, details in methods.items():
            if method.lower() in ["get", "post", "put", "delete"]:
                # Check for required fields
                if "operationId" not in details:
                    print(f"❌ Missing operationId: {method.upper()} {path}")
                    sys.exit(1)
                
                if "summary" not in details:
                    print(f"❌ Missing summary: {method.upper()} {path}")
                    sys.exit(1)
                
                if "responses" not in details:
                    print(f"❌ Missing responses: {method.upper()} {path}")
                    sys.exit(1)
    
    print("✅ OpenAPI specification coverage: 100%")
    print(f"✅ Documented endpoints: {len(paths)}")
    
    # Count total operations
    total_ops = sum(
        1 for methods in paths.values()
        for method in methods
        if method.lower() in ["get", "post", "put", "delete"]
    )
    print(f"✅ Total operations: {total_ops}")


if __name__ == "__main__":
    check_openapi_coverage()