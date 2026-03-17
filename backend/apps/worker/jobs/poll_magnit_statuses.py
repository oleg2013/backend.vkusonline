from __future__ import annotations

from datetime import UTC, datetime

import structlog
from sqlalchemy import select

from packages.core.db import async_session_factory
from packages.enums import ShipmentStatus
from packages.integrations.magnit.client import get_client
from packages.integrations.magnit.utils import map_magnit_status
from packages.models.shipment import Shipment, ShipmentStatusHistory

logger = structlog.get_logger(__name__)

TERMINAL_STATUSES = {ShipmentStatus.ISSUED, ShipmentStatus.RETURNED, ShipmentStatus.CANCELLED}


async def poll_magnit_statuses() -> None:
    logger.info("poll_magnit_statuses_started")
    try:
        async with async_session_factory() as db:
            stmt = select(Shipment).where(
                Shipment.provider == "magnit",
                Shipment.status.notin_([s.value for s in TERMINAL_STATUSES]),
            )
            result = await db.execute(stmt)
            shipments = list(result.scalars().all())

        if not shipments:
            logger.info("poll_magnit_no_active_shipments")
            return

        client = get_client()
        updated = 0

        for shipment in shipments:
            try:
                if not shipment.provider_shipment_id:
                    continue

                status_data = await client.get_order_status(shipment.provider_shipment_id)
                provider_status = status_data.get("status", "")
                new_status = map_magnit_status(provider_status)

                if new_status.value != shipment.status:
                    async with async_session_factory() as db:
                        s = await db.get(Shipment, shipment.id)
                        if s:
                            s.status = new_status.value
                            s.updated_at = datetime.now(UTC)

                            history = ShipmentStatusHistory(
                                shipment_id=s.id,
                                status=new_status.value,
                                provider_status=provider_status,
                                provider_data=status_data,
                                occurred_at=datetime.now(UTC),
                            )
                            db.add(history)
                            await db.commit()
                            updated += 1

            except Exception as e:
                logger.warning(
                    "poll_magnit_shipment_error",
                    shipment_id=shipment.id,
                    error=str(e),
                )

        logger.info("poll_magnit_statuses_completed", checked=len(shipments), updated=updated)
    except Exception as e:
        logger.exception("poll_magnit_statuses_failed", error=str(e))
