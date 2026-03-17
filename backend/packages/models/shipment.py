from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from packages.models.base import Base, TimestampMixin, generate_uuid


class Shipment(Base, TimestampMixin):
    __tablename__ = "shipments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    order_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True
    )

    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    provider_shipment_id: Mapped[str | None] = mapped_column(String(100), index=True)
    provider_order_number: Mapped[str | None] = mapped_column(String(100))

    status: Mapped[str] = mapped_column(String(30), nullable=False, default="created")
    tracking_number: Mapped[str | None] = mapped_column(String(100))

    pickup_point_id: Mapped[str | None] = mapped_column(String(100))
    pickup_point_name: Mapped[str | None] = mapped_column(String(500))

    weight_grams: Mapped[int] = mapped_column(Integer, nullable=False)
    parcel_size: Mapped[str | None] = mapped_column(String(5))

    label_url: Mapped[str | None] = mapped_column(String(500))

    provider_payload: Mapped[dict | None] = mapped_column(JSONB)

    status_history: Mapped[list[ShipmentStatusHistory]] = relationship(back_populates="shipment")


class ShipmentStatusHistory(Base):
    __tablename__ = "shipment_status_history"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    shipment_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("shipments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    provider_status: Mapped[str | None] = mapped_column(String(50))
    provider_data: Mapped[dict | None] = mapped_column(JSONB)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    shipment: Mapped[Shipment] = relationship(back_populates="status_history")
