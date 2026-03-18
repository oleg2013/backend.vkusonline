"""Worker job: poll delivery providers for shipment status changes.

Checks active shipments at 5Post and Magnit APIs. When provider reports
a status change (e.g. READY_FOR_PICKUP / ACCEPTED_AT_POINT), updates both
the Shipment record and the parent Order status via the state machine,
which triggers email notifications to the customer.

Key transitions:
  - 5Post READY_FOR_PICKUP / Magnit ACCEPTED_AT_POINT → Order.ready_for_pickup
  - 5Post ISSUED / Magnit ISSUED → Order.delivered
  - 5Post RETURNING / Magnit WAITING_RETURN → Order.client_dont_pickup
  - 5Post RETURNED / Magnit RETURNED_TO_PROVIDER → Order.returned_to_supplier

Rate limiting: max 30 requests/minute per provider (2 second delay between calls).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from packages.core.db import async_session_factory
from packages.enums import OrderStatus, ShipmentStatus
from packages.models.order import Order
from packages.models.shipment import Shipment, ShipmentStatusHistory
from packages.services import checkout as checkout_service

logger = structlog.get_logger("worker.poll_statuses")

# Shipment statuses that are final — no need to poll anymore
TERMINAL_STATUSES = {
    ShipmentStatus.ISSUED,
    ShipmentStatus.RETURNED,
    ShipmentStatus.CANCELLED,
    ShipmentStatus.LOST,
}

# Map ShipmentStatus → OrderStatus for automatic order updates
_SHIPMENT_TO_ORDER: dict[ShipmentStatus, OrderStatus] = {
    ShipmentStatus.READY_FOR_PICKUP: OrderStatus.READY_FOR_PICKUP,
    ShipmentStatus.ISSUED: OrderStatus.DELIVERED,
    ShipmentStatus.RETURNING: OrderStatus.CLIENT_DONT_PICKUP,
    ShipmentStatus.RETURNED: OrderStatus.RETURNED_TO_SUPPLIER,
}

# Order statuses that should NOT be auto-updated (already terminal or manual)
_ORDER_NO_AUTO_UPDATE = {
    OrderStatus.DELIVERED,
    OrderStatus.CANCELLED,
    OrderStatus.RETURNED_TO_SUPPLIER,
    OrderStatus.REFUNDED,
}


async def _poll_provider(provider: str) -> tuple[int, int]:
    """Poll a single provider for status changes. Returns (checked, updated)."""
    # Import provider-specific client and mapper
    if provider == "5post":
        from packages.integrations.fivepost.client import get_client
        from packages.integrations.fivepost.utils import map_fivepost_status as map_status
    elif provider == "magnit":
        from packages.integrations.magnit.client import get_client
        from packages.integrations.magnit.utils import map_magnit_status as map_status
    else:
        return 0, 0

    # Find active shipments
    async with async_session_factory() as db:
        stmt = select(Shipment).where(
            Shipment.provider == provider,
            Shipment.status.notin_([s.value for s in TERMINAL_STATUSES]),
        )
        result = await db.execute(stmt)
        shipments = list(result.scalars().all())

    if not shipments:
        return 0, 0

    client = get_client()
    updated = 0

    for i, shipment in enumerate(shipments):
        # Rate limit: 2 second delay between API calls (max 30/min)
        if i > 0:
            await asyncio.sleep(2)

        try:
            if not shipment.provider_shipment_id:
                continue

            # Get status from provider API
            if provider == "5post":
                status_obj = await client.get_order_status(shipment.provider_shipment_id)
                provider_status = status_obj.status_code
                provider_data = {
                    "status_code": status_obj.status_code,
                    "status_name": status_obj.status_name,
                    "events_count": len(status_obj.tracking_events),
                }
            else:
                # Magnit
                status_data = await client.get_order_status(shipment.provider_shipment_id)
                provider_status = status_data.get("status", "")
                provider_data = status_data

            new_shipment_status = map_status(provider_status)

            # Skip if no change
            if new_shipment_status.value == shipment.status:
                continue

            logger.info(
                "shipment_status_changed",
                provider=provider,
                shipment_id=shipment.id,
                order_id=shipment.order_id,
                old_status=shipment.status,
                new_status=new_shipment_status.value,
                provider_status=provider_status,
            )

            async with async_session_factory() as db:
                # Update shipment
                s = await db.get(Shipment, shipment.id)
                if not s:
                    continue

                s.status = new_shipment_status.value
                s.updated_at = datetime.now(UTC)

                history = ShipmentStatusHistory(
                    shipment_id=s.id,
                    status=new_shipment_status.value,
                    provider_status=provider_status,
                    provider_data=provider_data,
                    occurred_at=datetime.now(UTC),
                )
                db.add(history)

                # Auto-update Order status if applicable
                target_order_status = _SHIPMENT_TO_ORDER.get(new_shipment_status)
                if target_order_status:
                    order_stmt = (
                        select(Order)
                        .where(Order.id == s.order_id)
                        .options(selectinload(Order.items))
                    )
                    order_result = await db.execute(order_stmt)
                    order = order_result.scalar_one_or_none()

                    if order and order.status not in [st.value for st in _ORDER_NO_AUTO_UPDATE]:
                        try:
                            await checkout_service.update_order_status(
                                db, order, target_order_status
                            )
                            logger.info(
                                "order_status_auto_updated",
                                order_number=order.order_number,
                                old_status=order.status,
                                new_status=target_order_status.value,
                                trigger=f"{provider}:{provider_status}",
                            )
                        except Exception as exc:
                            # State machine may reject transition — log but don't fail
                            logger.warning(
                                "order_status_auto_update_rejected",
                                order_number=order.order_number,
                                target=target_order_status.value,
                                error=str(exc),
                            )

                await db.commit()
                updated += 1

        except Exception as exc:
            logger.warning(
                "poll_shipment_error",
                provider=provider,
                shipment_id=shipment.id,
                error=str(exc),
            )

    return len(shipments), updated


async def _with_lock(provider: str, coro):
    """Run coroutine under a Redis lock to prevent overlapping poll cycles."""
    from packages.core.redis import get_redis

    redis = await get_redis()
    lock_key = f"poll_lock:{provider}"

    # Try to acquire lock (TTL = 1 hour max to prevent stuck locks)
    acquired = await redis.set(lock_key, "1", nx=True, ex=3600)
    if not acquired:
        logger.info("poll_skipped_lock_held", provider=provider)
        return

    try:
        await coro
    finally:
        await redis.delete(lock_key)


async def poll_fivepost_statuses() -> None:
    """Poll 5Post API for shipment status changes (with lock)."""
    async def _run():
        logger.info("poll_fivepost_started")
        checked, updated = await _poll_provider("5post")
        logger.info("poll_fivepost_completed", checked=checked, updated=updated)

    try:
        await _with_lock("5post", _run())
    except Exception as exc:
        logger.exception("poll_fivepost_failed", error=str(exc))


async def poll_magnit_statuses() -> None:
    """Poll Magnit API for shipment status changes (with lock)."""
    async def _run():
        logger.info("poll_magnit_started")
        checked, updated = await _poll_provider("magnit")
        logger.info("poll_magnit_completed", checked=checked, updated=updated)

    try:
        await _with_lock("magnit", _run())
    except Exception as exc:
        logger.exception("poll_magnit_failed", error=str(exc))
