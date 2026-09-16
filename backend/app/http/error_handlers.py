"""HTTP adapters for framework-independent application errors."""

from fastapi import Request
from fastapi.responses import JSONResponse

from app.core.errors import ConflictError, DomainError, NotFoundError, ValidationError


def domain_error_status(error: DomainError) -> int:
    """Translate an expected domain failure to the existing HTTP status contract."""

    if isinstance(error, NotFoundError):
        return 404
    if isinstance(error, ConflictError):
        return 409
    if isinstance(error, ValidationError):
        return 422
    return 400


async def domain_error_handler(_: Request, error: DomainError) -> JSONResponse:
    """Preserve the established public error body: ``{\"detail\": message}``."""

    return JSONResponse(
        status_code=domain_error_status(error),
        content={"detail": error.message},
    )
