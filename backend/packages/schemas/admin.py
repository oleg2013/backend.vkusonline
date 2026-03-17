from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Admin order detail (extended)
# ---------------------------------------------------------------------------

class AdminOrderEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    event_type: str
    old_status: str | None = None
    new_status: str | None = None
    data: dict[str, Any] | None = None
    created_at: datetime


class AdminPaymentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    provider: str
    provider_payment_id: str | None = None
    status: str
    amount: float = Field(..., description="Amount in rubles")
    confirmation_type: str
    created_at: datetime
    updated_at: datetime


class AdminShipmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    provider: str
    provider_shipment_id: str | None = None
    provider_order_number: str | None = None
    status: str
    tracking_number: str | None = None
    pickup_point_id: str | None = None
    pickup_point_name: str | None = None
    weight_grams: int
    parcel_size: str | None = None
    label_url: str | None = None
    created_at: datetime
    updated_at: datetime


class AdminOrderItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    product_sku: str
    product_name: str
    quantity: int
    unit_price: float = Field(..., description="In rubles")
    total_price: float = Field(..., description="In rubles")
    weight_grams: int
    vat_rate: int


class AdminOrderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    order_number: str
    status: str

    # Owner
    user_id: str | None = None
    guest_session_id: str | None = None
    guest_order_token: str | None = None

    # Contact
    customer_email: str
    customer_phone: str
    customer_name: str

    # Delivery
    delivery_provider: str
    delivery_city: str
    delivery_address: str | None = None
    pickup_point_id: str | None = None
    pickup_point_name: str | None = None

    # Money (rubles)
    subtotal: float = Field(..., description="In rubles")
    discount_amount: float = Field(default=0, description="In rubles")
    customer_delivery_price: float = Field(..., description="In rubles")
    carrier_estimated_cost: float | None = Field(default=None, description="In rubles")
    carrier_actual_cost: float | None = Field(default=None, description="In rubles")
    total: float = Field(..., description="In rubles")

    # Discount snapshot
    applied_discounts: dict[str, Any] | None = None

    # Relations
    items: list[AdminOrderItemResponse] = Field(default_factory=list)
    events: list[AdminOrderEventResponse] = Field(default_factory=list)
    payments: list[AdminPaymentResponse] = Field(default_factory=list)
    shipments: list[AdminShipmentResponse] = Field(default_factory=list)

    # Timestamps
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Cache status
# ---------------------------------------------------------------------------

class CacheStatusResponse(BaseModel):
    provider: str
    points_count: int
    last_synced_at: datetime | None = None


# ---------------------------------------------------------------------------
# Job trigger
# ---------------------------------------------------------------------------

class JobTriggerResponse(BaseModel):
    job_name: str
    status: str = Field(..., description="e.g. 'started', 'already_running', 'failed'")
    message: str | None = None
