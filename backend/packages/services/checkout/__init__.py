from __future__ import annotations

from datetime import UTC, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from packages.core.config import settings
from packages.core.exceptions import ConflictError, NotFoundError, ValidationError
from packages.core.idempotency import check_idempotency_db, store_idempotency_db
from packages.core.security import generate_public_order_token
from packages.core.utils import generate_order_number
from packages.enums import OrderStatus, OrderType, PaymentMethod
from packages.services.order_state_machine import require_valid_transition
from packages.models.catalog import Product
from packages.models.order import Order, OrderEvent, OrderItem

logger = structlog.get_logger(__name__)


async def calculate_quote(
    db: AsyncSession,
    items: list[dict],
    delivery_price_kopecks: int,
    discount_amount_kopecks: int = 0,
    payment_method: str | None = None,
) -> dict:
    subtotal = 0
    items_detail = []

    for item_input in items:
        product = await _get_active_product(db, item_input["sku"])
        if not product:
            raise NotFoundError("Product", item_input["sku"])

        qty = item_input["quantity"]
        line_total = product.price * qty
        subtotal += line_total

        items_detail.append({
            "sku": product.sku,
            "name": product.name,
            "quantity": qty,
            "unit_price": product.price,
            "total_price": line_total,
            "weight_grams": product.weight_grams,
            "vat_rate": product.vat_rate,
        })

    # Card payment discount
    card_discount_kopecks = 0
    if payment_method == PaymentMethod.CARD and settings.card_payment_discount_percent > 0:
        card_discount_kopecks = int(subtotal * settings.card_payment_discount_percent / 100)

    total = subtotal - discount_amount_kopecks - card_discount_kopecks + delivery_price_kopecks

    return {
        "subtotal": subtotal,
        "discount_amount": discount_amount_kopecks,
        "card_discount_amount": card_discount_kopecks,
        "delivery_price": delivery_price_kopecks,
        "total": total,
        "items_detail": items_detail,
    }


async def create_order(
    db: AsyncSession,
    items: list[dict],
    customer_email: str,
    customer_phone: str,
    customer_name: str,
    delivery_provider: str,
    delivery_city: str,
    delivery_address: str | None,
    pickup_point_id: str | None,
    pickup_point_name: str | None,
    customer_delivery_price: int,
    carrier_estimated_cost: int | None,
    payment_method: str = PaymentMethod.CARD,
    discount_amount: int = 0,
    applied_discounts: dict | None = None,
    user_id: str | None = None,
    guest_session_id: str | None = None,
    idempotency_key: str | None = None,
) -> Order:
    # Idempotency check
    if idempotency_key:
        existing = await check_idempotency_db(db, idempotency_key)
        if existing:
            order_id = existing.resource_id
            stmt = select(Order).where(Order.id == order_id).options(
                selectinload(Order.items)
            )
            result = await db.execute(stmt)
            order = result.scalar_one_or_none()
            if order:
                return order

    # Calculate from server-side prices (includes card discount if applicable)
    quote = await calculate_quote(
        db, items, customer_delivery_price, discount_amount, payment_method
    )

    # Build applied_discounts with card discount info
    discounts = applied_discounts or {}
    if quote.get("card_discount_amount", 0) > 0:
        discounts["card_payment_discount"] = {
            "type": "card_payment",
            "percent": settings.card_payment_discount_percent,
            "amount_kopecks": quote["card_discount_amount"],
        }

    # Determine order type and initial status
    if payment_method == PaymentMethod.COD:
        order_type = OrderType.CODFLOW
        initial_status = OrderStatus.PENDING_CONFIRMATION
    else:
        order_type = OrderType.PREPAID
        initial_status = OrderStatus.PENDING_PAYMENT

    order_number = generate_order_number()
    # Always generate public token (for order tracking URL)
    public_token = generate_public_order_token()

    order = Order(
        order_number=order_number,
        user_id=user_id,
        guest_session_id=guest_session_id,
        guest_order_token=public_token,
        order_type=order_type,
        status=initial_status,
        payment_method=payment_method,
        customer_email=customer_email,
        customer_phone=customer_phone,
        customer_name=customer_name,
        delivery_provider=delivery_provider,
        delivery_city=delivery_city,
        delivery_address=delivery_address,
        pickup_point_id=pickup_point_id,
        pickup_point_name=pickup_point_name,
        subtotal=quote["subtotal"],
        discount_amount=quote["discount_amount"] + quote.get("card_discount_amount", 0),
        customer_delivery_price=customer_delivery_price,
        carrier_estimated_cost=carrier_estimated_cost,
        total=quote["total"],
        applied_discounts=discounts if discounts else None,
        idempotency_key=idempotency_key,
    )
    db.add(order)
    await db.flush()

    for item_detail in quote["items_detail"]:
        oi = OrderItem(
            order_id=order.id,
            product_sku=item_detail["sku"],
            product_name=item_detail["name"],
            quantity=item_detail["quantity"],
            unit_price=item_detail["unit_price"],
            total_price=item_detail["total_price"],
            weight_grams=item_detail["weight_grams"],
            vat_rate=item_detail["vat_rate"],
        )
        db.add(oi)

    event = OrderEvent(
        order_id=order.id,
        event_type="order_created",
        new_status=initial_status,
        created_at=datetime.now(UTC),
    )
    db.add(event)

    if idempotency_key:
        await store_idempotency_db(
            db, idempotency_key, "order", order.id, 201, {"order_number": order_number}
        )

    await db.flush()
    logger.info(
        "order_created",
        order_number=order_number,
        total=quote["total"],
        payment_method=payment_method,
    )

    # Reload order with eager-loaded items before dispatching event
    # (avoids SQLAlchemy lazy-load greenlet error in async handler)
    stmt = select(Order).where(Order.id == order.id).options(selectinload(Order.items))
    result = await db.execute(stmt)
    order = result.scalar_one()

    # Dispatch order_created event (for email notifications)
    try:
        from packages.services.events import event_dispatcher
        await event_dispatcher.dispatch("order_created", {"order": order})
    except Exception as exc:
        logger.warning("event_dispatch_failed", event="order_created", error=str(exc))

    return order


async def update_order_status(
    db: AsyncSession,
    order: Order,
    new_status: OrderStatus,
    event_data: dict | None = None,
    *,
    skip_validation: bool = False,
) -> Order:
    old_status = order.status

    if not skip_validation:
        require_valid_transition(order.order_type, old_status, new_status)

    order.status = new_status
    order.updated_at = datetime.now(UTC)

    event = OrderEvent(
        order_id=order.id,
        event_type="status_changed",
        old_status=old_status,
        new_status=new_status,
        data=event_data,
        created_at=datetime.now(UTC),
    )
    db.add(event)
    await db.flush()

    logger.info(
        "order_status_changed",
        order_number=order.order_number,
        old_status=old_status,
        new_status=new_status,
    )

    # Reload order with eager-loaded items before dispatching event
    stmt = select(Order).where(Order.id == order.id).options(selectinload(Order.items))
    result = await db.execute(stmt)
    order = result.scalar_one()

    # Dispatch order_status_changed event (for email notifications)
    try:
        from packages.services.events import event_dispatcher
        await event_dispatcher.dispatch("order_status_changed", {
            "order": order,
            "old_status": old_status,
            "new_status": new_status,
        })
    except Exception as exc:
        logger.warning("event_dispatch_failed", event="order_status_changed", error=str(exc))

    return order


async def cancel_order(
    db: AsyncSession,
    order: Order,
) -> Order:
    # Validation is done inside update_order_status via state machine
    return await update_order_status(db, order, OrderStatus.CANCELLED)


async def get_order_by_number(
    db: AsyncSession,
    order_number: str,
) -> Order | None:
    stmt = (
        select(Order)
        .where(Order.order_number == order_number)
        .options(selectinload(Order.items), selectinload(Order.events))
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def _get_active_product(db: AsyncSession, sku: str) -> Product | None:
    stmt = select(Product).where(Product.sku == sku, Product.is_active.is_(True))
    result = await db.execute(stmt)
    return result.scalar_one_or_none()
