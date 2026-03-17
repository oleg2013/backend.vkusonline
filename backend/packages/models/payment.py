from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from packages.models.base import Base, TimestampMixin, generate_uuid


class Payment(Base, TimestampMixin):
    __tablename__ = "payments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    order_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True
    )

    provider: Mapped[str] = mapped_column(String(20), nullable=False, default="yookassa")
    provider_payment_id: Mapped[str | None] = mapped_column(String(100), unique=True, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)

    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    amount: Mapped[int] = mapped_column(Integer, nullable=False)  # kopecks

    confirmation_url: Mapped[str | None] = mapped_column(Text)
    confirmation_type: Mapped[str] = mapped_column(String(20), default="redirect")

    provider_payload: Mapped[dict | None] = mapped_column(JSONB)

    events: Mapped[list[PaymentEvent]] = relationship(back_populates="payment")


class PaymentEvent(Base):
    __tablename__ = "payment_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    payment_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("payments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    old_status: Mapped[str | None] = mapped_column(String(30))
    new_status: Mapped[str | None] = mapped_column(String(30))
    provider_data: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    payment: Mapped[Payment] = relationship(back_populates="events")
