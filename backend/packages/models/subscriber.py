from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from packages.models.base import Base


class Subscriber(Base):
    __tablename__ = "subscribers"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    email: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False, index=True
    )
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    unsubscribe_token: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        nullable=False,
        index=True,
        default=lambda: uuid.uuid4().hex,
    )
    source: Mapped[str] = mapped_column(
        String(50), default="footer", nullable=False
    )  # footer, checkout, popup
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        nullable=False,
    )
