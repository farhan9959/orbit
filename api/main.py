"""FastAPI application factory."""

from __future__ import annotations

import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from api.config import get_settings
from api.observability import configure_logging, correlation_middleware, request_id_var
from api.routes import auth, health, live, resources


def error_response(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "request_id": request_id_var.get(),
            }
        },
    )


def create_app() -> FastAPI:
    settings = get_settings()
    settings.require_usable_secret()
    configure_logging(settings.log_level)

    app = FastAPI(title="ORBIT", version="0.1.0", docs_url="/api/docs")
    app.middleware("http")(correlation_middleware)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return error_response(exc.status_code, f"http_{exc.status_code}", str(exc.detail))

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        return error_response(422, "validation_error", "request failed validation")

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        """Never leak a traceback; the detail goes to the log keyed by request id."""
        return error_response(500, "internal_error", "internal server error")

    app.include_router(health.router)
    app.include_router(auth.router, prefix="/api/v1")
    app.include_router(resources.router)
    app.include_router(live.router)
    return app


app = create_app()
_ = uuid
