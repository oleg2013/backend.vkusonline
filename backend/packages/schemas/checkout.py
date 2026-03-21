from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


# ---------------------------------------------------------------------------
# Shared sub-schemas
# ---------------------------------------------------------------------------

class CheckoutItemIn(BaseModel):
    sku: str = Field(..., min_length=1, max_length=50)
    quantity: int = Field(..., ge=1)


class CheckoutItemDetail(BaseModel):
    sku: str
    product_name: str
    quantity: int
    unit_price: float = Field(..., description="Price per unit in rubles")
    total_price: float = Field(..., description="Line total in rubles")
    weight_grams: int


# ---------------------------------------------------------------------------
# Quote (pre-order price calculation)
# ---------------------------------------------------------------------------

class CheckoutQuoteRequest(BaseModel):
    items: list[CheckoutItemIn] = Field(..., min_length=1)
    delivery_provider: str = Field(..., description="'5post' or 'magnit'")
    pickup_point_id: str | None = Field(default=None, description="Required for pickup delivery")
    city: str = Field(..., max_length=255)
    delivery_address: str | None = Field(default=None, description="Full address for courier delivery")
    payment_method: str | None = Field(default=None, description="'card' or 'cod'")
    delivery_price: float | None = Field(default=None, description="Pre-calculated delivery price in rubles")


class CheckoutQuoteResponse(BaseModel):
    subtotal: float = Field(..., description="Item subtotal in rubles")
    discount_amount: float = Field(default=0, description="Total discount in rubles")
    card_discount_amount: float = Field(default=0, description="Card payment discount in rubles")
    delivery_price: float = Field(..., description="Delivery price for the customer in rubles")
    total: float = Field(..., description="Grand total in rubles")
    items_detail: list[CheckoutItemDetail] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Create order
# ---------------------------------------------------------------------------

class CreateOrderRequest(BaseModel):
    items: list[CheckoutItemIn] = Field(..., min_length=1)
    delivery_provider: str = Field(..., description="'5post' or 'magnit'")
    delivery_city: str = Field(..., max_length=255)
    delivery_address: str | None = None
    delivery_price: float | None = Field(default=None, description="Customer-facing delivery price in rubles")
    pickup_point_id: str | None = None
    pickup_point_name: str | None = None
    customer_email: EmailStr
    customer_phone: str = Field(..., min_length=1, max_length=20)
    customer_name: str = Field(..., min_length=1, max_length=255)
    recipient_name: str | None = Field(default=None, max_length=255, description="Alternate recipient name (gift orders)")
    recipient_phone: str | None = Field(default=None, max_length=20, description="Alternate recipient phone (gift orders)")
    idempotency_key: str = Field(..., min_length=1, max_length=64)
    payment_method: str = Field(..., description="'card' or 'cod'")
    create_account: bool = Field(default=False, description="Create user account during checkout")
    password: str | None = Field(default=None, min_length=8, max_length=128, description="Password for new account")


# ---------------------------------------------------------------------------
# Order responses
# ---------------------------------------------------------------------------

class OrderItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    product_sku: str
    product_name: str
    quantity: int
    unit_price: float = Field(..., description="Price per unit in rubles")
    total_price: float = Field(..., description="Line total in rubles")


class DeliveryInfoResponse(BaseModel):
    provider: str
    city: str
    address: str | None = None
    pickup_point_id: str | None = None
    pickup_point_name: str | None = None


class OrderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    order_number: str
    status: str
    payment_method: str | None = None
    items: list[OrderItemResponse] = Field(default_factory=list)
    subtotal: float = Field(..., description="In rubles")
    discount_amount: float = Field(default=0, description="In rubles")
    delivery_price: float = Field(..., description="In rubles")
    total: float = Field(..., description="In rubles")
    delivery: DeliveryInfoResponse | None = None
    created_at: datetime
    guest_order_token: str | None = Field(default=None, description="Token for guest order tracking")
    confirmation_url: str | None = Field(default=None, description="YooKassa payment URL (card payments)")


class OrderStatusResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    order_number: str
    status: str
    payment_status: str | None = None
    shipment_status: str | None = None


# ---------------------------------------------------------------------------
# Order list (summaries)
# ---------------------------------------------------------------------------

class OrderSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    order_number: str
    status: str
    total: float = Field(..., description="In rubles")
    items_count: int
    created_at: datetime


class OrderListResponse(BaseModel):
    orders: list[OrderSummary] = Field(default_factory=list)
    total: int = Field(..., description="Total number of orders matching the query")
