"""
FastAPI middleware for error handling and idempotency
"""

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from typing import Callable
import time
from .error_codes import APIError, InternalError
from .idempotency import IdempotencyManager


async def error_handler_middleware(request: Request, call_next: Callable) -> Response:
    """Global error handler middleware"""
    try:
        response = await call_next(request)
        return response
    except APIError as e:
        return JSONResponse(
            status_code=e.status_code,
            content=e.to_dict()
        )
    except Exception as e:
        # Log the error here
        print(f"Unhandled error: {str(e)}")
        error = InternalError()
        return JSONResponse(
            status_code=500,
            content=error.to_dict()
        )


async def idempotency_middleware(
    request: Request,
    call_next: Callable,
    idempotency_manager: IdempotencyManager
) -> Response:
    """Handle idempotency for POST requests"""
    
    # Only apply to POST requests
    if request.method != "POST":
        return await call_next(request)
    
    # Get idempotency key from header
    idempotency_key = request.headers.get("Idempotency-Key")
    
    if not idempotency_key:
        # No idempotency key, process normally
        return await call_next(request)
    
    # Check for cached response
    endpoint = request.url.path
    cached = await idempotency_manager.get_cached_response(idempotency_key, endpoint)
    
    if cached:
        return JSONResponse(
            status_code=cached["status_code"],
            content=cached["response"],
            headers={"X-Idempotent-Replay": "true"}
        )
    
    # Check if currently processing
    if await idempotency_manager.is_processing(idempotency_key, endpoint):
        # Return 429 to indicate retry
        return JSONResponse(
            status_code=429,
            content={
                "error": "Request is currently being processed",
                "error_code": "CONCURRENT_REQUEST",
                "error_details": {
                    "idempotency_key": idempotency_key,
                    "retry_after": 5
                }
            }
        )
    
    # Acquire lock
    acquired = await idempotency_manager.acquire_lock(idempotency_key, endpoint)
    
    if not acquired:
        return JSONResponse(
            status_code=429,
            content={
                "error": "Failed to acquire processing lock",
                "error_code": "LOCK_ACQUISITION_FAILED"
            }
        )
    
    try:
        # Process request
        response = await call_next(request)
        
        # Cache successful response (2xx)
        if 200 <= response.status_code < 300:
            # Read response body
            body = b""
            async for chunk in response.body_iterator:
                body += chunk
            
            import json
            response_data = json.loads(body.decode())
            
            await idempotency_manager.cache_response(
                idempotency_key,
                endpoint,
                response_data,
                response.status_code
            )
            
            # Recreate response
            return JSONResponse(
                status_code=response.status_code,
                content=response_data
            )
        
        return response
        
    finally:
        # Always release lock
        await idempotency_manager.release_lock(idempotency_key, endpoint)