from __future__ import annotations


class AppError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 400,
        details: dict | None = None,
    ):
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}
        super().__init__(message)


class NotFoundError(AppError):
    def __init__(self, entity: str, identifier: str | None = None):
        detail = f"{entity} not found"
        if identifier:
            detail = f"{entity} '{identifier}' not found"
        super().__init__(code="NOT_FOUND", message=detail, status_code=404)


class AuthError(AppError):
    def __init__(self, message: str = "Authentication required"):
        super().__init__(code="AUTH_ERROR", message=message, status_code=401)


class ForbiddenError(AppError):
    def __init__(self, message: str = "Access denied"):
        super().__init__(code="FORBIDDEN", message=message, status_code=403)


class ConflictError(AppError):
    def __init__(self, message: str):
        super().__init__(code="CONFLICT", message=message, status_code=409)


class ValidationError(AppError):
    def __init__(self, message: str, details: dict | None = None):
        super().__init__(
            code="VALIDATION_ERROR", message=message, status_code=422, details=details
        )


class RateLimitError(AppError):
    def __init__(self, message: str = "Too many requests"):
        super().__init__(code="RATE_LIMIT", message=message, status_code=429)


class ProviderError(AppError):
    def __init__(self, provider: str, message: str, details: dict | None = None):
        super().__init__(
            code=f"PROVIDER_{provider.upper()}_ERROR",
            message=message,
            status_code=502,
            details=details,
        )
