from __future__ import annotations

from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import select

from packages.core.db import async_session_factory
from packages.enums import PaymentStatus
from packages.integrations.yookassa.client import get_client
from packages.models.payment import Payment
from packages.services import payments as payment_service

logger = structlog.get_logger(__name__)


async def reconcile_pending_payments() -> None:
    logger.info("reconcile_payments_started")
    try:
        async with async_session_factory() as db:
            cutoff = datetime.now(UTC) - timedelta(minutes=10)
            stmt = select(Payment).where(
                Payment.status == PaymentStatus.PENDING,
                Payment.provider_payment_id.isnot(None),
                Payment.created_at < cutoff,
            )
            result = await db.execute(stmt)
            payments = list(result.scalars().all())

        if not payments:
            logger.info("reconcile_no_pending_payments")
            return

        client = get_client()
        reconciled = 0

        for payment in payments:
            try:
                if not payment.provider_payment_id:
                    continue

                provider_data = await client.get_payment(payment.provider_payment_id)
                provider_status = provider_data.status

                status_map = {
                    "succeeded": PaymentStatus.SUCCEEDED,
                    "canceled": PaymentStatus.CANCELLED,
                    "waiting_for_capture": PaymentStatus.WAITING_CAPTURE,
                    "pending": PaymentStatus.PENDING,
                }

                new_status = status_map.get(provider_status)
                if new_status and new_status != payment.status:
                    async with async_session_factory() as db:
                        p = await db.get(Payment, payment.id)
                        if p:
                            await payment_service.update_payment_from_provider(
                                db,
                                p,
                                p.provider_payment_id,
                                new_status,
                                provider_payload=provider_data.model_dump(),
                            )
                            if new_status == PaymentStatus.SUCCEEDED:
                                await payment_service.process_payment_success(db, p)
                            elif new_status == PaymentStatus.CANCELLED:
                                await payment_service.process_payment_cancelled(db, p)
                            await db.commit()
                            reconciled += 1

            except Exception as e:
                logger.warning(
                    "reconcile_payment_error",
                    payment_id=payment.id,
                    error=str(e),
                )

        logger.info("reconcile_payments_completed", checked=len(payments), reconciled=reconciled)
    except Exception as e:
        logger.exception("reconcile_payments_failed", error=str(e))
