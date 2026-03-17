from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


# ---------------------------------------------------------------------------
# Error detail
# ---------------------------------------------------------------------------

class ErrorDetail(BaseModel):
    """Structured error information returned inside ``ErrorResponse``."""

    code: str = Field(..., description="Machine-readable error code, e.g. 'validation_error'")
    message: str = Field(..., description="Human-readable error message")
    details: Any | None = Field(default=None, description="Optional extra payload (field errors, etc.)")


# ---------------------------------------------------------------------------
# Envelope: success
# ---------------------------------------------------------------------------

class SuccessResponse(BaseModel, Generic[T]):
    """Generic success envelope.

    Usage::

        SuccessResponse[UserResponse](data=user)
    """

    model_config = ConfigDict(from_attributes=True)

    ok: bool = Field(default=True, description="Always ``True`` for success responses")
    data: T
    request_id: str | None = Field(default=None, description="Correlation / trace id")


# ---------------------------------------------------------------------------
# Envelope: error
# ---------------------------------------------------------------------------

class ErrorResponse(BaseModel):
    """Standard error envelope returned on 4xx / 5xx."""

    ok: bool = Field(default=False, description="Always ``False`` for error responses")
    error: ErrorDetail
    request_id: str | None = Field(default=None, description="Correlation / trace id")
