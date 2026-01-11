"""
Error handling middleware for FastAPI application.
"""
from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi import HTTPException
from typing import Any
import logging
from services.freelancer_client import FreelancerAPIError

logger = logging.getLogger(__name__)


async def freelancer_exception_handler(request: Request, exc: FreelancerAPIError):
    """Handle Freelancer API errors."""
    logger.error(f"Freelancer API error: {exc.message}")

    return JSONResponse(
        status_code=exc.status_code or 500,
        content={
            "status": "error",
            "error_type": "freelancer_api",
            "message": exc.message,
            "retry_after": exc.retry_after
        }
    )


async def general_exception_handler(request: Request, exc: Exception):
    """Handle all unhandled exceptions."""
    logger.exception(f"Unhandled exception: {str(exc)}")

    return JSONResponse(
        status_code=500,
        content={
            "status": "error",
            "error_type": "internal_server_error",
            "message": "An unexpected error occurred"
        }
    )
