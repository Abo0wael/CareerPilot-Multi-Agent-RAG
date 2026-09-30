"""Maps domain exceptions to HTTP responses.

Handlers are registered from most to least specific; FastAPI picks the
handler for the closest class in the exception's MRO.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from src.domain.exceptions import (
    CareerPilotError,
    CVParsingError,
    EmptyFieldError,
    IndexNotFoundError,
    InvalidEntityError,
    JobNotFoundError,
    LLMError,
    LLMRateLimitError,
    WorkflowStateError,
)

logger = logging.getLogger(__name__)

RATE_LIMIT_RETRY_AFTER_SECONDS = "30"

_STATUS_BY_ERROR: dict[type[CareerPilotError], int] = {
    JobNotFoundError: status.HTTP_404_NOT_FOUND,
    CVParsingError: status.HTTP_400_BAD_REQUEST,
    EmptyFieldError: status.HTTP_400_BAD_REQUEST,
    InvalidEntityError: status.HTTP_400_BAD_REQUEST,
    WorkflowStateError: status.HTTP_400_BAD_REQUEST,
    IndexNotFoundError: status.HTTP_503_SERVICE_UNAVAILABLE,
    LLMError: status.HTTP_502_BAD_GATEWAY,  # LLMResponseParseError and Groq API errors
    CareerPilotError: status.HTTP_500_INTERNAL_SERVER_ERROR,
}


async def _handle_rate_limit(request: Request, exc: LLMRateLimitError) -> JSONResponse:
    logger.error("LLM rate limit: %s", exc)
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"detail": "Groq API rate limit reached. Please wait a moment and retry.", "error": str(exc)},
        headers={"Retry-After": RATE_LIMIT_RETRY_AFTER_SECONDS},
    )


async def _handle_domain_error(request: Request, exc: CareerPilotError) -> JSONResponse:
    code = next(c for cls, c in _STATUS_BY_ERROR.items() if isinstance(exc, cls))
    if code >= status.HTTP_500_INTERNAL_SERVER_ERROR:
        logger.error("%s: %s", type(exc).__name__, exc)
    prefix = "CV parsing failed: " if isinstance(exc, CVParsingError) else ""
    return JSONResponse(status_code=code, content={"detail": f"{prefix}{exc}"})


def register_error_handlers(app: FastAPI) -> None:
    """Attach all domain-exception handlers to *app*."""
    app.add_exception_handler(LLMRateLimitError, _handle_rate_limit)
    for error_cls in _STATUS_BY_ERROR:
        app.add_exception_handler(error_cls, _handle_domain_error)
