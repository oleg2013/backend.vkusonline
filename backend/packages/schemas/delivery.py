from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Pickup points
# ---------------------------------------------------------------------------

class WorkScheduleItem(BaseModel):
    """Single day working hours."""
    day: str = Field(..., description="Day code: MON, TUE, WED, THU, FRI, SAT, SUN")
    opens_at: str = Field("", description="Opening time, e.g. '09:00'")
    closes_at: str = Field("", description="Closing time, e.g. '21:00'")


class PickupPointResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    type: str | None = Field(default=None, description="PVZ, postamat, etc.")
    city: str
    full_address: str
    lat: float
    lon: float
    distance_km: float | None = Field(default=None, description="Distance from reference point")
    cash_allowed: bool | None = None
    card_allowed: bool | None = None
    work_schedule: list[WorkScheduleItem] = Field(default_factory=list, description="Working hours by day")


# ---------------------------------------------------------------------------
# Delivery estimate
# ---------------------------------------------------------------------------

class DeliveryEstimateItemIn(BaseModel):
    sku: str = Field(..., min_length=1, max_length=50)
    quantity: int = Field(..., ge=1)


class DeliveryEstimateRequest(BaseModel):
    items: list[DeliveryEstimateItemIn] = Field(..., min_length=1)
    pickup_point_id: str | None = None
    city: str = Field(..., max_length=255)


class DeliveryEstimateResponse(BaseModel):
    provider: str
    estimated_cost: float = Field(..., description="Estimated delivery cost in rubles")
    estimated_days_min: int
    estimated_days_max: int


# ---------------------------------------------------------------------------
# Available delivery options
# ---------------------------------------------------------------------------

class DeliveryOptionResponse(BaseModel):
    provider: str
    name: str
    description: str | None = None
    available: bool


# ---------------------------------------------------------------------------
# Magnit cities
# ---------------------------------------------------------------------------

class MagnitCityResponse(BaseModel):
    city: str
    pickup_points_count: int


class NearestCityResponse(BaseModel):
    city: str
    distance_km: float
    pickup_points_count: int


# ---------------------------------------------------------------------------
# Checkout: delivery options for a city
# ---------------------------------------------------------------------------

class DeliveryOptionsCartItem(BaseModel):
    sku: str = Field(..., min_length=1, max_length=50)
    quantity: int = Field(..., ge=1)


class DeliveryOptionsRequest(BaseModel):
    city: str = Field(..., max_length=255)
    cart_items: list[DeliveryOptionsCartItem] = Field(..., min_length=1)


class ProviderOption(BaseModel):
    provider: str
    name: str
    available: bool
    pickup_points_count: int = 0
    min_delivery_cost: float | None = None
    estimated_days_min: int | None = None
    estimated_days_max: int | None = None


class DeliveryOptionsResponse(BaseModel):
    providers: list[ProviderOption]
    card_payment_discount_percent: float


# ---------------------------------------------------------------------------
# Checkout: estimate delivery for a specific PVZ
# ---------------------------------------------------------------------------

class EstimateDeliveryRequest(BaseModel):
    provider: str = Field(..., description="'5post' or 'magnit'")
    pickup_point_id: str = Field(..., min_length=1)
    cart_items: list[DeliveryOptionsCartItem] = Field(..., min_length=1)


class EstimateDeliveryResponse(BaseModel):
    provider: str
    pickup_point_id: str
    pickup_point_name: str | None = None
    delivery_cost: float = Field(..., description="Cost in rubles")
    estimated_days_min: int | None = None
    estimated_days_max: int | None = None
    cash_allowed: bool = False
    card_allowed: bool = False
