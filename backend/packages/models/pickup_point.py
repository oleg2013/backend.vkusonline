from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from packages.models.base import Base, generate_uuid


class PickupPointCache(Base):
    __tablename__ = "pickup_points_cache"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    provider: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    external_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    point_type: Mapped[str | None] = mapped_column(String(50))
    city: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    full_address: Mapped[str] = mapped_column(String(500), nullable=False)
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lon: Mapped[float] = mapped_column(Float, nullable=False)
    cash_allowed: Mapped[bool | None] = mapped_column()
    card_allowed: Mapped[bool | None] = mapped_column()
    max_weight_grams: Mapped[int | None] = mapped_column(Integer)
    rates: Mapped[dict | None] = mapped_column(JSONB)
    cell_limits: Mapped[dict | None] = mapped_column(JSONB)
    raw_data: Mapped[dict | None] = mapped_column(JSONB)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
