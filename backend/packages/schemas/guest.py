from __future__ import annotations

import re

from pydantic import BaseModel, Field, field_validator

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


class GuestBootstrapRequest(BaseModel):
    guest_session_id: str = Field(
        ...,
        min_length=36,
        max_length=36,
        description="Client-generated UUID v4 for the guest session",
    )

    @field_validator("guest_session_id")
    @classmethod
    def validate_uuid_format(cls, v: str) -> str:
        if not _UUID_RE.match(v):
            raise ValueError("guest_session_id must be a valid UUID (xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx)")
        return v


class GuestBootstrapResponse(BaseModel):
    guest_session_id: str
    created: bool = Field(..., description="True if a new session was created, False if it already existed")
