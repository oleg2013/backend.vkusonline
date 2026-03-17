from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Product
# ---------------------------------------------------------------------------

class ProductResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    sku: str
    name: str
    family_slug: str | None = Field(default=None, description="Slug of the parent product family")
    variant_label: str | None = None
    price: float = Field(..., description="Price in rubles")
    weight_grams: int
    vat_rate: int = Field(..., description="VAT rate percentage, e.g. 22")
    is_active: bool
    image_url: str | None = None


# ---------------------------------------------------------------------------
# Product family
# ---------------------------------------------------------------------------

class ProductFamilyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    slug: str
    name: str
    category: str
    subcategory: str | None = None
    description: str | None = None
    image_url: str | None = None
    tags: list[str] | dict[str, Any] | None = None
    products: list[ProductResponse] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Collection
# ---------------------------------------------------------------------------

class CollectionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str | None = None
    product_skus: list[str] = Field(default_factory=list)
