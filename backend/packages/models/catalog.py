from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from packages.models.base import Base, TimestampMixin, generate_uuid


class ProductFamily(Base, TimestampMixin):
    __tablename__ = "product_families"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    subcategory: Mapped[str | None] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text)
    image_url: Mapped[str | None] = mapped_column(String(500))
    tags: Mapped[dict | None] = mapped_column(JSONB)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    products: Mapped[list[Product]] = relationship(back_populates="family")


class Product(Base, TimestampMixin):
    __tablename__ = "products"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    sku: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    family_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("product_families.id"),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    variant_label: Mapped[str | None] = mapped_column(String(100))
    price: Mapped[int] = mapped_column(Integer, nullable=False)  # kopecks
    weight_grams: Mapped[int] = mapped_column(Integer, nullable=False)
    volume_ml: Mapped[int | None] = mapped_column(Integer)
    dimensions_mm: Mapped[dict | None] = mapped_column(JSONB)
    vat_rate: Mapped[int] = mapped_column(Integer, default=20, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Extended product fields (from frontend catalog)
    description: Mapped[str | None] = mapped_column(Text)
    composition: Mapped[str | None] = mapped_column(Text)
    product_type: Mapped[str | None] = mapped_column(String(50))  # tea, coffee, hot_chocolate
    sub_type: Mapped[str | None] = mapped_column(String(50))  # herbal, black, espresso, etc.
    product_format: Mapped[str | None] = mapped_column(String(50))  # loose, bags, beans, ground
    taste: Mapped[dict | None] = mapped_column(JSONB)  # ["spicy", "sweet", ...]
    images: Mapped[dict | None] = mapped_column(JSONB)  # ["url1", "url2", ...]

    family: Mapped[ProductFamily | None] = relationship(back_populates="products")

    @property
    def price_rub(self) -> float:
        return self.price / 100
