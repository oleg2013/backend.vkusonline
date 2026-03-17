from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------

class CartItemAdd(BaseModel):
    product_sku: str = Field(..., min_length=1, max_length=50)
    quantity: int = Field(..., ge=1, description="Number of units to add")


class CartItemUpdate(BaseModel):
    quantity: int = Field(..., ge=1, description="New quantity for the cart item")


# ---------------------------------------------------------------------------
# Responses
# ---------------------------------------------------------------------------

class CartItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    product_sku: str
    product_name: str
    quantity: int
    unit_price: float = Field(..., description="Price per unit in rubles")
    total_price: float = Field(..., description="quantity * unit_price in rubles")


class CartResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    items: list[CartItemResponse] = Field(default_factory=list)
    subtotal: float = Field(..., description="Sum of item totals in rubles")
    items_count: int = Field(..., description="Total number of items in the cart")
