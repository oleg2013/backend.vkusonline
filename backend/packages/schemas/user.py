from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


# ---------------------------------------------------------------------------
# User read
# ---------------------------------------------------------------------------

class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: EmailStr
    phone: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    display_name: str | None = None
    created_at: datetime


# ---------------------------------------------------------------------------
# User update
# ---------------------------------------------------------------------------

class UserUpdateRequest(BaseModel):
    first_name: str | None = Field(default=None, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)
    phone: str | None = Field(default=None, max_length=20)


# ---------------------------------------------------------------------------
# Address
# ---------------------------------------------------------------------------

class AddressCreate(BaseModel):
    label: str | None = Field(default=None, max_length=100, description="Friendly name, e.g. 'Home'")
    city: str = Field(..., max_length=255)
    street: str | None = Field(default=None, max_length=255)
    house: str | None = Field(default=None, max_length=50)
    apartment: str | None = Field(default=None, max_length=50)
    postal_code: str | None = Field(default=None, max_length=10)
    full_address: str = Field(..., description="Full human-readable address string")
    lat: float | None = None
    lon: float | None = None
    is_default: bool = False


class AddressUpdate(BaseModel):
    label: str | None = Field(default=None, max_length=100)
    city: str | None = Field(default=None, max_length=255)
    street: str | None = Field(default=None, max_length=255)
    house: str | None = Field(default=None, max_length=50)
    apartment: str | None = Field(default=None, max_length=50)
    postal_code: str | None = Field(default=None, max_length=10)
    full_address: str | None = None
    lat: float | None = None
    lon: float | None = None
    is_default: bool | None = None


class AddressResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    label: str | None = None
    city: str
    street: str | None = None
    house: str | None = None
    apartment: str | None = None
    postal_code: str | None = None
    full_address: str
    lat: float | None = None
    lon: float | None = None
    is_default: bool
    created_at: datetime
    updated_at: datetime
