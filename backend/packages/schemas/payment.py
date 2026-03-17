from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Create payment
# ---------------------------------------------------------------------------

class PaymentCreateRequest(BaseModel):
    order_number: str = Field(..., min_length=1, max_length=30)
    idempotency_key: str = Field(..., min_length=1, max_length=64)
    confirmation_type: str = Field(default="redirect", description="YooKassa confirmation type")


class PaymentCreateResponse(BaseModel):
    payment_id: str
    confirmation_url: str | None = Field(
        default=None, description="Redirect URL for the customer to complete payment"
    )
    status: str


# ---------------------------------------------------------------------------
# Payment status
# ---------------------------------------------------------------------------

class PaymentStatusResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    payment_id: str
    status: str
    amount: float = Field(..., description="Payment amount in rubles")
    provider_payment_id: str | None = None
