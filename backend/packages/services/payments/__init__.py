from __future__ import annotations

import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.core.exceptions import ConflictError, NotFoundError
from packages.enums import OrderStatus, PaymentStatus
from packages.models.order import Order
from packages.models.payment import Payment, PaymentEvent
from packages.services.checkout import update_order_status

logger = structlog.get_logger(__name__)


async def create_payment(
    db: AsyncSession,
    order: Order,
    idempotency_key: str,
    confirmation_type: str = "redirect",
) -> Payment:
    if order.status not in (OrderStatus.PENDING_PAYMENT,):
        raise ConflictError(f"Cannot create payment for order in status '{order.status}'")

    # Check for existing pending payment with same idempotency key
    existing = await db.execute(
        select(Payment).where(Payment.idempotency_key == idempotency_key)
    )
    existing_payment = existing.scalar_one_or_none()
    if existing_payment:
        return existing_payment

    payment = Payment(
        order_id=order.id,
        provider="yookassa",
        idempotency_key=idempotency_key,
        status=PaymentStatus.PENDING,
        amount=order.total,
        confirmation_type=confirmation_type,
    )
    db.add(payment)
    await db.flush()

    logger.info("payment_created", payment_id=payment.id, order_number=order.order_number)
    return payment


async def update_payment_from_provider(
    db: AsyncSession,
    payment: Payment,
    provider_payment_id: str,
    new_status: PaymentStatus,
    confirmation_url: str | None = None,
    provider_payload: dict | None = None,
) -> Payment:
    old_status = payment.status
    payment.provider_payment_id = provider_payment_id
    payment.status = new_status
    if confirmation_url:
        payment.confirmation_url = confirmation_url
    if provider_payload:
        payment.provider_payload = provider_payload

    event = PaymentEvent(
        payment_id=payment.id,
        event_type="provider_update",
        old_status=old_status,
        new_status=new_status,
        provider_data=provider_payload,
        created_at=datetime.now(UTC),
    )
    db.add(event)
    await db.flush()
    return payment


async def process_payment_success(
    db: AsyncSession,
    payment: Payment,
) -> None:
    order = await db.get(Order, payment.order_id)
    if not order:
        raise NotFoundError("Order", payment.order_id)

    if order.status == OrderStatus.PENDING_PAYMENT:
        await update_order_status(db, order, OrderStatus.PAID, {"payment_id": payment.id})
        logger.info("order_paid", order_number=order.order_number, payment_id=payment.id)


async def process_payment_cancelled(
    db: AsyncSession,
    payment: Payment,
) -> None:
    order = await db.get(Order, payment.order_id)
    if not order:
        return

    # Check if there are other successful payments
    other_payments = await db.execute(
        select(Payment).where(
            Payment.order_id == order.id,
            Payment.id != payment.id,
            Payment.status == PaymentStatus.SUCCEEDED,
        )
    )
    if not other_payments.scalar_one_or_none():
        logger.info(
            "payment_cancelled_no_other_success",
            order_number=order.order_number,
            payment_id=payment.id,
        )


async def get_payment_by_provider_id(
    db: AsyncSession,
    provider_payment_id: str,
) -> Payment | None:
    stmt = select(Payment).where(Payment.provider_payment_id == provider_payment_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def get_payments_for_order(
    db: AsyncSession,
    order_id: str,
) -> list[Payment]:
    stmt = select(Payment).where(Payment.order_id == order_id).order_by(Payment.created_at.desc())
    result = await db.execute(stmt)
    return list(result.scalars().all())
