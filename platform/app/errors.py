from __future__ import annotations

import logging
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("certivo.errors")


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, details: list | None = None):
        self.status, self.code, self.message, self.details = status, code, message, details


def _body(request: Request, code: str, message: str, details: list | None = None) -> dict:
    err = {"code": code, "message": message,
           "request_id": getattr(request.state, "request_id", None)}
    if details:
        err["details"] = details
    return {"error": err}


def install_error_handling(app: FastAPI) -> None:
    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        request.state.request_id = f"req_{uuid.uuid4().hex[:16]}"
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError):
        return JSONResponse(_body(request, exc.code, exc.message, exc.details),
                            status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError):
        details = [{"loc": [str(p) for p in e["loc"]], "msg": e["msg"], "type": e["type"]}
                   for e in exc.errors()]
        return JSONResponse(_body(request, "validation_error", "Request validation failed",
                                  details), status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException):
        return JSONResponse(_body(request, f"http_{exc.status_code}", str(exc.detail)),
                            status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        # Never leak internals to the caller; the request ID lets us find the details in the logs.
        request_id = getattr(request.state, "request_id", None)
        log.error("Unhandled error (request_id=%s)", request_id, exc_info=exc)
        headers = {"X-Request-ID": request_id} if request_id else {}
        return JSONResponse(_body(request, "internal_error", "An internal error occurred."),
                            status_code=500, headers=headers)
