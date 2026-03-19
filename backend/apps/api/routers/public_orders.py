"""Public order tracking endpoints — no auth required, token is the secret."""

from __future__ import annotations

import structlog
from fastapi import APIRouter

from apps.api.deps import DbSession
from packages.core.exceptions import ConflictError, NotFoundError
from packages.enums import OrderStatus, OrderType, PaymentStatus
from packages.services import checkout as checkout_service
from packages.services import orders as orders_service
from packages.services import payments as payment_service
from packages.services.order_state_machine import build_stepper, get_status_label

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["public-orders"])


async def _find_order(db, token_or_number: str):
    """Find order by public token or order number."""
    order = await orders_service.get_order_by_public_token(db, token_or_number)
    if not order:
        order = await checkout_service.get_order_by_number(db, token_or_number)
    return order


@router.get("/orders/track/{token}")
async def track_order(token: str, db: DbSession):
    order = await _find_order(db, token)
    if not order:
        raise NotFoundError("Order", "token")

    stepper = build_stepper(order.order_type, order.status)

    items = [
        {
            "product_sku": item.product_sku,
            "product_name": item.product_name,
            "quantity": item.quantity,
            "unit_price": item.unit_price / 100,
            "total_price": item.total_price / 100,
        }
        for item in order.items
    ]

    can_confirm = (
        order.order_type == OrderType.CODFLOW
        and order.status == OrderStatus.PENDING_CONFIRMATION
    )

    can_cancel = order.status in {
        OrderStatus.PENDING_PAYMENT,
        OrderStatus.PENDING_CONFIRMATION,
        OrderStatus.DRAFT,
    }

    # Get confirmation_url from the latest payment (for pending_payment orders)
    confirmation_url = None
    if order.status == OrderStatus.PENDING_PAYMENT:
        from sqlalchemy import select
        from packages.models.payment import Payment
        stmt = select(Payment).where(Payment.order_id == order.id).order_by(Payment.created_at.desc())
        result = await db.execute(stmt)
        payment = result.scalars().first()
        if payment:
            confirmation_url = payment.confirmation_url

    # Lookup PVZ details from cache (address, work schedule)
    pvz_address = None
    pvz_work_schedule = None
    if order.pickup_point_id and order.delivery_provider:
        from sqlalchemy import select as sa_select
        from packages.models.pickup_point import PickupPointCache
        pvz_stmt = sa_select(PickupPointCache).where(
            PickupPointCache.provider == order.delivery_provider,
            PickupPointCache.external_id == order.pickup_point_id,
        )
        pvz_result = await db.execute(pvz_stmt)
        pvz = pvz_result.scalar_one_or_none()
        if pvz:
            pvz_address = pvz.full_address
            if pvz.raw_data:
                raw_schedule = pvz.raw_data.get("work_schedule") or []
                if raw_schedule:
                    pvz_work_schedule = [
                        {
                            "day": e.get("day", ""),
                            "opens_at": e.get("opens_at", ""),
                            "closes_at": e.get("closes_at", ""),
                        }
                        for e in raw_schedule
                        if isinstance(e, dict) and e.get("day")
                    ]

    provider_labels = {"magnit": "Магнит", "5post": "5Post"}

    return {
        "ok": True,
        "data": {
            "order_number": order.order_number,
            "order_type": order.order_type,
            "status": order.status,
            "status_label": get_status_label(order.status),
            "customer_name": order.customer_name,
            "customer_email": order.customer_email,
            "total": order.total / 100,
            "subtotal": order.subtotal / 100,
            "discount_amount": order.discount_amount / 100,
            "delivery_price": order.customer_delivery_price / 100,
            "payment_method": order.payment_method,
            "items": items,
            "delivery": {
                "provider": order.delivery_provider,
                "provider_name": provider_labels.get(order.delivery_provider, order.delivery_provider),
                "city": order.delivery_city,
                "pickup_point_name": order.pickup_point_name,
                "pickup_point_address": pvz_address,
                "work_schedule": pvz_work_schedule,
            },
            "stepper": stepper,
            "can_confirm": can_confirm,
            "can_cancel": can_cancel,
            "confirmation_url": confirmation_url,
            "created_at": order.created_at.isoformat() if order.created_at else None,
        },
    }


@router.post("/orders/{token}/confirm")
async def confirm_cod_order(token: str, db: DbSession):
    order = await _find_order(db, token)
    if not order:
        raise NotFoundError("Order", "token")

    if order.order_type != OrderType.CODFLOW:
        raise ConflictError("Only COD orders can be confirmed via link")

    if order.status != OrderStatus.PENDING_CONFIRMATION:
        raise ConflictError(
            f"Order is already in status '{get_status_label(order.status)}'"
        )

    order = await checkout_service.update_order_status(
        db, order, OrderStatus.CONFIRMED_BY_CLIENT
    )
    await db.commit()

    return {
        "ok": True,
        "data": {
            "order_number": order.order_number,
            "status": order.status,
            "status_label": get_status_label(order.status),
        },
    }


@router.post("/orders/{token}/check-payment")
async def check_payment_status(token: str, db: DbSession):
    """Check payment status with YooKassa and update order if paid.

    Called when user returns from YooKassa payment page to the tracking page.
    """
    order = await _find_order(db, token)
    if not order:
        raise NotFoundError("Order", "token")

    if order.status != OrderStatus.PENDING_PAYMENT:
        return {
            "ok": True,
            "data": {"status": order.status, "status_label": get_status_label(order.status), "changed": False},
        }

    # Find the payment for this order and check with YooKassa
    from sqlalchemy import select
    from packages.models.payment import Payment
    from packages.integrations.yookassa.client import get_client

    stmt = select(Payment).where(
        Payment.order_id == order.id,
        Payment.provider_payment_id.isnot(None),
    ).order_by(Payment.created_at.desc())
    result = await db.execute(stmt)
    payment = result.scalars().first()

    if not payment or not payment.provider_payment_id:
        return {
            "ok": True,
            "data": {"status": order.status, "status_label": get_status_label(order.status), "changed": False},
        }

    try:
        client = get_client()
        provider_data = await client.get_payment(payment.provider_payment_id)

        if provider_data.status == "succeeded" and payment.status != PaymentStatus.SUCCEEDED:
            await payment_service.update_payment_from_provider(
                db, payment, payment.provider_payment_id,
                PaymentStatus.SUCCEEDED, provider_payload=provider_data.model_dump(),
            )
            await payment_service.process_payment_success(db, payment)
            await db.commit()
            # Re-fetch order to get updated status
            order = await orders_service.get_order_by_public_token(db, token)
            logger.info("payment_check_updated", order=order.order_number, status=order.status)
            return {
                "ok": True,
                "data": {"status": order.status, "status_label": get_status_label(order.status), "changed": True},
            }
    except Exception as exc:
        logger.warning("payment_check_error", error=str(exc))

    return {
        "ok": True,
        "data": {"status": order.status, "status_label": get_status_label(order.status), "changed": False},
    }


@router.post("/orders/{token}/cancel")
async def cancel_order_by_token(token: str, db: DbSession):
    order = await _find_order(db, token)
    if not order:
        raise NotFoundError("Order", "token")

    cancellable = {
        OrderStatus.PENDING_PAYMENT,
        OrderStatus.PENDING_CONFIRMATION,
        OrderStatus.DRAFT,
    }
    if order.status not in cancellable:
        raise ConflictError(
            f"Cannot cancel order in status '{get_status_label(order.status)}'"
        )

    order = await checkout_service.update_order_status(
        db, order, OrderStatus.CANCELLED
    )
    await db.commit()

    return {
        "ok": True,
        "data": {
            "order_number": order.order_number,
            "status": order.status,
            "status_label": get_status_label(order.status),
        },
    }
