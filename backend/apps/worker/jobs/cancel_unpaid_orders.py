"""Worker job: auto-cancel PREPAID orders stuck in pending_payment for too long."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import select

from packages.core.db import async_session_factory
from packages.enums import OrderStatus, OrderType
from packages.models.order import Order
from packages.services import checkout as checkout_service

logger = structlog.get_logger(__name__)

UNPAID_TIMEOUT_MINUTES = 30


async def cancel_unpaid_orders() -> None:
    """Cancel PREPAID orders that have been in pending_payment for too long."""
    logger.info("cancel_unpaid_orders_started")
    try:
        async with async_session_factory() as db:
            cutoff = datetime.now(UTC) - timedelta(minutes=UNPAID_TIMEOUT_MINUTES)
            stmt = select(Order).where(
                Order.order_type == OrderType.PREPAID,
                Order.status == OrderStatus.PENDING_PAYMENT,
                Order.created_at < cutoff,
            )
            result = await db.execute(stmt)
            orders = list(result.scalars().all())

            if not orders:
                logger.info("cancel_unpaid_no_orders")
                return

            cancelled = 0
            for order in orders:
                try:
                    await checkout_service.update_order_status(
                        db, order, OrderStatus.CANCELLED,
                        event_data={"reason": "auto_cancel_unpaid", "timeout_minutes": UNPAID_TIMEOUT_MINUTES},
                    )
                    cancelled += 1
                    logger.info("order_auto_cancelled", order_number=order.order_number)
                except Exception as exc:
                    logger.warning("cancel_unpaid_error", order=order.order_number, error=str(exc))

            await db.commit()
            logger.info("cancel_unpaid_completed", checked=len(orders), cancelled=cancelled)
    except Exception as exc:
        logger.exception("cancel_unpaid_failed", error=str(exc))
