"""
Global exception handlers for the application.
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.services.ai_gateway.exceptions import (
    AIConnectionException,
    AIInvalidResponseException,
    AIProviderNotFoundException,
    AIResponseException,
    AIServiceException,
    AITimeoutException,
)


def register_exception_handlers(app: FastAPI) -> None:
    """
    Register all custom exception handlers.
    """

    @app.exception_handler(AIProviderNotFoundException)
    async def provider_not_found_handler(
        request: Request,
        exc: AIProviderNotFoundException,
    ):
        return JSONResponse(
            status_code=404,
            content={
                "success": False,
                "error": "Provider Not Found",
                "message": str(exc),
            },
        )

    @app.exception_handler(AITimeoutException)
    async def timeout_handler(
        request: Request,
        exc: AITimeoutException,
    ):
        return JSONResponse(
            status_code=504,
            content={
                "success": False,
                "error": "Gateway Timeout",
                "message": str(exc),
            },
        )

    @app.exception_handler(AIConnectionException)
    async def connection_handler(
        request: Request,
        exc: AIConnectionException,
    ):
        return JSONResponse(
            status_code=503,
            content={
                "success": False,
                "error": "Service Unavailable",
                "message": str(exc),
            },
        )

    @app.exception_handler(AIInvalidResponseException)
    async def invalid_response_handler(
        request: Request,
        exc: AIInvalidResponseException,
    ):
        return JSONResponse(
            status_code=502,
            content={
                "success": False,
                "error": "Invalid AI Response",
                "message": str(exc),
            },
        )

    @app.exception_handler(AIResponseException)
    async def ai_response_handler(
        request: Request,
        exc: AIResponseException,
    ):
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "success": False,
                "error": "AI Service Error",
                "message": exc.detail,
            },
        )

    @app.exception_handler(AIServiceException)
    async def ai_service_handler(
        request: Request,
        exc: AIServiceException,
    ):
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": "AI Service Error",
                "message": str(exc),
            },
        )