"""Database models and setup for the delivery emulator.

All tables use the ``emul_`` prefix to coexist with the main application
tables in the same PostgreSQL database.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, relationship

from config import settings

engine = create_async_engine(settings.database_url, pool_size=5, max_overflow=5)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ── 5Post ────────────────────────────────────────────────────────────

class EmulFivePostOrder(Base):
    __tablename__ = "emul_fivepost_orders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(UUID(as_uuid=True), default=uuid.uuid4, unique=True, nullable=False, index=True)
    sender_order_id = Column(String(255), unique=True, nullable=False, index=True)
    client_order_id = Column(String(255), nullable=True)
    client_name = Column(String(255), nullable=True)
    client_phone = Column(String(50), nullable=True)
    client_email = Column(String(255), nullable=True)
    receiver_location = Column(String(255), nullable=True)
    sender_location = Column(String(255), nullable=True)
    status = Column(String(50), nullable=False, default="NEW")
    execution_status = Column(String(80), nullable=False, default="CREATED")
    mile_type = Column(String(50), nullable=True)
    payment_value = Column(Float, nullable=True)
    payment_type = Column(String(50), nullable=True)
    order_data = Column(JSONB, nullable=True)
    cargo_id = Column(UUID(as_uuid=True), default=uuid.uuid4, nullable=False)
    sender_cargo_id = Column(String(255), nullable=True)
    barcode = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)

    history = relationship("EmulFivePostStatusHistory", back_populates="order", cascade="all, delete-orphan")


class EmulFivePostStatusHistory(Base):
    __tablename__ = "emul_fivepost_status_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(UUID(as_uuid=True), ForeignKey("emul_fivepost_orders.order_id", ondelete="CASCADE"), nullable=False, index=True)
    status = Column(String(50), nullable=False)
    execution_status = Column(String(80), nullable=False)
    mile_type = Column(String(50), nullable=True)
    error_desc = Column(Text, nullable=True)
    change_date = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

    order = relationship("EmulFivePostOrder", back_populates="history")


# ── Magnit ───────────────────────────────────────────────────────────

class EmulMagnitOrder(Base):
    __tablename__ = "emul_magnit_orders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tracking_number = Column(UUID(as_uuid=True), default=uuid.uuid4, unique=True, nullable=False, index=True)
    customer_order_id = Column(String(255), nullable=True, index=True)
    external_order_id = Column(String(255), nullable=True)
    pickup_point_key = Column(String(255), nullable=True)
    recipient_phone = Column(String(50), nullable=True)
    recipient_name = Column(String(255), nullable=True)
    status = Column(String(80), nullable=False, default="NEW")
    warehouse_id = Column(String(255), nullable=True)
    return_type = Column(String(50), nullable=True, default="return")
    order_data = Column(JSONB, nullable=True)
    parcel_id = Column(UUID(as_uuid=True), default=uuid.uuid4, nullable=False)
    parcel_barcode = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)

    history = relationship("EmulMagnitStatusHistory", back_populates="order", cascade="all, delete-orphan")


class EmulMagnitStatusHistory(Base):
    __tablename__ = "emul_magnit_status_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tracking_number = Column(UUID(as_uuid=True), ForeignKey("emul_magnit_orders.tracking_number", ondelete="CASCADE"), nullable=False, index=True)
    status = Column(String(80), nullable=False)
    timestamp = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

    order = relationship("EmulMagnitOrder", back_populates="history")


# ── Helpers ──────────────────────────────────────────────────────────

async def init_db() -> None:
    """Create all emulator tables (safe to call repeatedly)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db():
    """Async session dependency for FastAPI."""
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
