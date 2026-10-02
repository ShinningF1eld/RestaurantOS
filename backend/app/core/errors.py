"""Framework-independent errors raised by application and domain code."""

from collections.abc import Mapping


class DomainError(Exception):
    """An expected business failure with a stable machine-readable code."""

    code = "domain_error"

    def __init__(
        self,
        message: str,
        *,
        details: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details = dict(details) if details is not None else None


class NotFoundError(DomainError):
    code = "not_found"


class ConflictError(DomainError):
    code = "conflict"


class ValidationError(DomainError):
    code = "validation_error"


class ForbiddenError(DomainError):
    code = "forbidden"
