from __future__ import annotations

import structlog
from fastapi import FastAPI, Request
from fastapi.responses import ORJSONResponse

from packages.core.exceptions import AppError

logger = structlog.get_logger(__name__)


def register_exception_handlers(app: FastAPI) -> None:
    """Register exception handlers on the FastAPI app.

    Uses FastAPI exception handlers instead of BaseHTTPMiddleware
    to avoid breaking SQLAlchemy async greenlet context.
    """

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> ORJSONResponse:
        request_id = getattr(request.state, "request_id", None)
        logger.warning(
            "app_error",
            code=exc.code,
            message=exc.message,
            status=exc.status_code,
        )
        return ORJSONResponse(
            status_code=exc.status_code,
            content={
                "ok": False,
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "details": exc.details,
                },
                "request_id": request_id,
            },
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception) -> ORJSONResponse:
        request_id = getattr(request.state, "request_id", None)
        logger.exception("unhandled_error", error=str(exc))
        return ORJSONResponse(
            status_code=500,
            content={
                "ok": False,
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": "An internal error occurred",
                    "details": {},
                },
                "request_id": request_id,
            },
        )
