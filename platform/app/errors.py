from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi import HTTPException as FastAPIHTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("certivo.errors")


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, details: list | None = None,
                 headers: dict[str, str] | None = None):
        self.status, self.code, self.message = status, code, message
        self.details, self.headers = details, headers


class HttpRejection(FastAPIHTTPException):
    """A request refused while its body is being read (413 too large, 408 too slow).

    It must subclass FastAPI's HTTPException: FastAPI re-raises that class untouched, but turns any
    other exception raised during body parsing into a plain 400.
    """

    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(status_code=status_code, detail=message)
        self.code = code


def error_body(request_id: str | None, code: str, message: str,
               details: list | None = None) -> dict:
    err = {"code": code, "message": message, "request_id": request_id}
    if details:
        err["details"] = details
    return {"error": err}


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def install_error_handling(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError):
        request.state.error_code = exc.code  # read by the access log (app/observability.py)
        return JSONResponse(error_body(_request_id(request), exc.code, exc.message, exc.details),
                            status_code=exc.status, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError):
        request.state.error_code = "validation_error"
        details = [{"loc": [str(p) for p in e["loc"]], "msg": e["msg"], "type": e["type"]}
                   for e in exc.errors()]
        return JSONResponse(error_body(_request_id(request), "validation_error",
                                       "Request validation failed", details), status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException):
        code = exc.code if isinstance(exc, HttpRejection) else f"http_{exc.status_code}"
        request.state.error_code = code
        return JSONResponse(error_body(_request_id(request), code, str(exc.detail)),
                            status_code=exc.status_code, headers=getattr(exc, "headers", None))

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        # Never leak internals to the caller; the request ID lets us find the details in the logs.
        from app.hardening import security_header_items  # local import: avoids a cycle

        request_id = _request_id(request)
        request.state.error_code = "internal_error"
        log.error("Unhandled error", extra={"request_id": request_id}, exc_info=exc)
        headers = dict(security_header_items(request.app.state.settings, request.url.path))
        if request_id:
            headers["X-Request-ID"] = request_id
        return JSONResponse(error_body(request_id, "internal_error", "An internal error occurred."),
                            status_code=500, headers=headers)
