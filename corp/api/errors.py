"""One error shape for the UI to branch on.

Every error body carries ``detail`` (FastAPI's default, kept for compatibility)
and ``error: {code, message}``. Domain exceptions map to fixed codes.
"""

import logging

from fastapi import FastAPI, Request, status
from fastapi.exceptions import HTTPException, RequestValidationError
from fastapi.responses import JSONResponse

from corp.core.state.machine import InvalidTransitionError
from corp.workers.adapters.registry import AdapterConfigError
from corp.workers.providers.factory import ProviderConfigError

logger = logging.getLogger(__name__)

_STATUS_CODES = {
    400: "bad_request",
    401: "unauthorized",
    404: "not_found",
    409: "conflict",
    422: "validation_error",
    500: "internal_error",
    503: "service_unavailable",
}


def _body(status_code: int, message: str, code: str | None = None) -> dict:
    return {
        "detail": message,
        "error": {"code": code or _STATUS_CODES.get(status_code, "error"), "message": message},
    }


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(HTTPException)
    async def _http(request: Request, exc: HTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_body(exc.status_code, str(exc.detail)),
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        body = _body(422, "Request validation failed", "validation_error")
        body["errors"] = exc.errors()
        return JSONResponse(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, content=body)

    @app.exception_handler(InvalidTransitionError)
    async def _transition(request: Request, exc: InvalidTransitionError) -> JSONResponse:
        return JSONResponse(status_code=409, content=_body(409, str(exc), "invalid_transition"))

    @app.exception_handler(ProviderConfigError)
    async def _provider(request: Request, exc: ProviderConfigError) -> JSONResponse:
        return JSONResponse(
            status_code=503, content=_body(503, str(exc), "provider_not_configured")
        )

    @app.exception_handler(AdapterConfigError)
    async def _adapter(request: Request, exc: AdapterConfigError) -> JSONResponse:
        return JSONResponse(status_code=400, content=_body(400, str(exc), "adapter_not_configured"))

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(status_code=500, content=_body(500, "Internal server error"))
