from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from packages.models.base import Base, TimestampMixin, generate_uuid


class Order(Base, TimestampMixin):
    __tablename__ = "orders"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    order_number: Mapped[str] = mapped_column(String(30), unique=True, nullable=False, index=True)

    # Owner
    user_id: Mapped[str | None] = mapped_column(String(36), index=True)
    guest_session_id: Mapped[str | None] = mapped_column(String(36), index=True)
    guest_order_token: Mapped[str | None] = mapped_column(String(64), unique=True, index=True)

    # Order type & status
    order_type: Mapped[str] = mapped_column(String(10), nullable=False, default="prepaid", index=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="draft", index=True)

    # Contact
    customer_email: Mapped[str] = mapped_column(String(255), nullable=False)
    customer_phone: Mapped[str] = mapped_column(String(20), nullable=False)
    customer_name: Mapped[str] = mapped_column(String(255), nullable=False)

    # Delivery
    delivery_provider: Mapped[str] = mapped_column(String(20), nullable=False)
    delivery_city: Mapped[str] = mapped_column(String(255), nullable=False)
    delivery_address: Mapped[str | None] = mapped_column(Text)
    pickup_point_id: Mapped[str | None] = mapped_column(String(100))
    pickup_point_name: Mapped[str | None] = mapped_column(String(500))

    # Money (kopecks)
    subtotal: Mapped[int] = mapped_column(Integer, nullable=False)
    discount_amount: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    customer_delivery_price: Mapped[int] = mapped_column(Integer, nullable=False)
    carrier_estimated_cost: Mapped[int | None] = mapped_column(Integer)
    carrier_actual_cost: Mapped[int | None] = mapped_column(Integer)
    total: Mapped[int] = mapped_column(Integer, nullable=False)

    # Payment
    payment_method: Mapped[str | None] = mapped_column(String(10))

    # Discount snapshot
    applied_discounts: Mapped[dict | None] = mapped_column(JSONB)

    # Idempotency
    idempotency_key: Mapped[str | None] = mapped_column(String(64), unique=True, index=True)

    # Relations
    items: Mapped[list[OrderItem]] = relationship(back_populates="order")
    events: Mapped[list[OrderEvent]] = relationship(back_populates="order")


class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    order_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_sku: Mapped[str] = mapped_column(String(50), nullable=False)
    product_name: Mapped[str] = mapped_column(String(255), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price: Mapped[int] = mapped_column(Integer, nullable=False)
    total_price: Mapped[int] = mapped_column(Integer, nullable=False)
    weight_grams: Mapped[int] = mapped_column(Integer, nullable=False)
    vat_rate: Mapped[int] = mapped_column(Integer, default=22, nullable=False)

    order: Mapped[Order] = relationship(back_populates="items")


class OrderEvent(Base):
    __tablename__ = "order_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    order_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    old_status: Mapped[str | None] = mapped_column(String(30))
    new_status: Mapped[str | None] = mapped_column(String(30))
    data: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    order: Mapped[Order] = relationship(back_populates="events")
