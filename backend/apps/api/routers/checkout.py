from __future__ import annotations

import uuid
from datetime import UTC, datetime

import structlog
from fastapi import APIRouter
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from apps.api.deps import CurrentUserId, DbSession, GuestSessionId, Redis, RequestId
from packages.core.config import settings
from packages.core.rate_limit import check_rate_limit
from packages.enums import PaymentMethod, PaymentStatus
from packages.services import auth as auth_service
from packages.integrations.yookassa.client import YooKassaClient
from packages.integrations.yookassa.receipt_builder import build_receipt
from packages.models.order import Order
from packages.schemas.checkout import CheckoutQuoteRequest, CreateOrderRequest
from packages.schemas.delivery import (
    DeliveryOptionsRequest,
    EstimateDeliveryRequest,
)
from packages.services import checkout as checkout_service
from packages.services import delivery as delivery_service
from packages.services import guests as guest_service
from packages.services import payments as payment_service

logger = structlog.get_logger("checkout")

router = APIRouter(tags=["checkout"])

yookassa_client = YooKassaClient(
    shop_id=settings.yookassa_shop_id,
    secret_key=settings.yookassa_secret_key,
)


# ---------------------------------------------------------------------------
# Delivery options & estimate
# ---------------------------------------------------------------------------


@router.post("/checkout/delivery-options")
async def delivery_options(
    body: DeliveryOptionsRequest,
    db: DbSession,
    request_id: RequestId,
):
    """Get available delivery providers for a city with minimum costs."""
    cart_items = [{"sku": i.sku, "quantity": i.quantity} for i in body.cart_items]
    result = await delivery_service.get_delivery_options(db, body.city, cart_items)
    return {"ok": True, "data": result, "request_id": request_id}


@router.post("/checkout/estimate-delivery")
async def estimate_delivery(
    body: EstimateDeliveryRequest,
    db: DbSession,
    request_id: RequestId,
):
    """Calculate exact delivery cost for a specific pickup point."""
    cart_items = [{"sku": i.sku, "quantity": i.quantity} for i in body.cart_items]
    result = await delivery_service.estimate_delivery_for_pvz(
        db, body.provider, body.pickup_point_id, cart_items
    )
    return {"ok": True, "data": result, "request_id": request_id}


# ---------------------------------------------------------------------------
# Quote
# ---------------------------------------------------------------------------


@router.post("/checkout/quote")
async def quote(
    body: CheckoutQuoteRequest,
    db: DbSession,
    request_id: RequestId,
):
    delivery_price_kopecks = int(body.delivery_price * 100) if body.delivery_price else 0
    items = [{"sku": i.sku, "quantity": i.quantity} for i in body.items]
    quote_data = await checkout_service.calculate_quote(
        db, items, delivery_price_kopecks, payment_method=body.payment_method
    )
    return {
        "ok": True,
        "data": {
            "subtotal": quote_data["subtotal"] / 100,
            "discount_amount": quote_data["discount_amount"] / 100,
            "card_discount_amount": quote_data.get("card_discount_amount", 0) / 100,
            "delivery_price": quote_data["delivery_price"] / 100,
            "total": quote_data["total"] / 100,
            "items_detail": [
                {
                    "sku": i["sku"],
                    "name": i["name"],
                    "quantity": i["quantity"],
                    "unit_price": i["unit_price"] / 100,
                    "total_price": i["total_price"] / 100,
                    "weight_grams": i["weight_grams"],
                }
                for i in quote_data["items_detail"]
            ],
        },
        "request_id": request_id,
    }


# ---------------------------------------------------------------------------
# Create order helpers
# ---------------------------------------------------------------------------


async def _create_yookassa_payment(db, order, request_id) -> str | None:
    """Create YooKassa payment for card orders and return confirmation_url."""
    # Reload order with items to avoid lazy loading greenlet errors
    stmt = select(Order).where(Order.id == order.id).options(selectinload(Order.items))
    result = await db.execute(stmt)
    order = result.scalar_one()

    idempotency_key = f"order-pay-{order.order_number}-{uuid.uuid4().hex[:8]}"
    payment = await payment_service.create_payment(db, order, idempotency_key)

    # Build receipt items from order items
    # When card discount applies, distribute it proportionally across items
    card_discount_kopecks = 0
    if order.applied_discounts and "card_payment_discount" in order.applied_discounts:
        card_discount_kopecks = order.applied_discounts["card_payment_discount"]["amount_kopecks"]

    subtotal_kopecks = sum(item.total_price for item in order.items)
    receipt_items = []

    discount_distributed = 0
    for idx, item in enumerate(order.items):
        unit_price = item.unit_price
        if card_discount_kopecks > 0 and subtotal_kopecks > 0:
            # Distribute discount proportionally per item line
            if idx == len(order.items) - 1:
                # Last item gets remaining discount to avoid rounding errors
                line_discount = card_discount_kopecks - discount_distributed
            else:
                line_discount = int(card_discount_kopecks * item.total_price / subtotal_kopecks)
            discount_distributed += line_discount
            # Reduce unit price proportionally
            unit_price = max(1, item.unit_price - int(line_discount / item.quantity))

        receipt_items.append({
            "name": item.product_name,
            "quantity": item.quantity,
            "unit_price_kopecks": unit_price,
            "vat_rate": item.vat_rate,
        })

    # Add delivery as a service item
    if order.customer_delivery_price > 0:
        receipt_items.append({
            "name": "Доставка",
            "quantity": 1,
            "unit_price_kopecks": order.customer_delivery_price,
            "vat_rate": 0,
            "payment_subject": "service",
        })

    receipt = build_receipt(
        items=receipt_items,
        customer_email=order.customer_email,
        customer_phone=order.customer_phone,
        customer_name=order.customer_name,
    )

    provider_result = await yookassa_client.create_payment(
        amount_rub=order.total / 100,
        receipt=receipt,
        return_url=f"{settings.effective_yookassa_return_url}/{order.guest_order_token}",
        idempotency_key=idempotency_key,
        description=f"Заказ {order.order_number}",
    )

    confirmation_url = None
    if provider_result.confirmation:
        confirmation_url = provider_result.confirmation.confirmation_url

    await payment_service.update_payment_from_provider(
        db,
        payment,
        provider_payment_id=provider_result.id,
        new_status=PaymentStatus.PENDING,
        confirmation_url=confirmation_url,
        provider_payload={"id": provider_result.id, "status": provider_result.status},
    )

    return confirmation_url


# ---------------------------------------------------------------------------
# Create order (guest)
# ---------------------------------------------------------------------------


@router.post("/guest/checkout/create-order")
async def create_guest_order(
    body: CreateOrderRequest,
    guest_session_id: GuestSessionId,
    db: DbSession,
    redis: Redis,
    request_id: RequestId,
):
    await check_rate_limit(redis, f"checkout:{guest_session_id}", max_requests=5, window_seconds=60)
    await guest_service.validate_guest_session(db, guest_session_id)

    items = [{"sku": i.sku, "quantity": i.quantity} for i in body.items]
    delivery_price_kopecks = int(body.delivery_price * 100) if body.delivery_price else 0

    order = await checkout_service.create_order(
        db,
        items=items,
        customer_email=body.customer_email,
        customer_phone=body.customer_phone,
        customer_name=body.customer_name,
        delivery_provider=body.delivery_provider,
        delivery_city=body.delivery_city,
        delivery_address=body.delivery_address,
        pickup_point_id=body.pickup_point_id,
        pickup_point_name=body.pickup_point_name,
        customer_delivery_price=delivery_price_kopecks,
        carrier_estimated_cost=None,
        payment_method=body.payment_method,
        guest_session_id=guest_session_id,
        idempotency_key=body.idempotency_key,
    )

    # Auto-create YooKassa payment for card orders
    confirmation_url = None
    if body.payment_method == PaymentMethod.CARD:
        confirmation_url = await _create_yookassa_payment(db, order, request_id)

    # Optional: create user account during checkout (password auto-generated)
    auth_tokens = None
    if body.create_account:
        import secrets
        import string
        _alphabet = string.ascii_lowercase + string.digits
        generated_password = "".join(secrets.choice(_alphabet) for _ in range(8))
        try:
            user, access_token, refresh_token = await auth_service.register_user(
                db,
                email=body.customer_email,
                password=generated_password,
                phone=body.customer_phone,
                first_name=body.customer_name,
            )
            order.user_id = user.id
            await db.flush()
            auth_tokens = {
                "access_token": access_token,
                "refresh_token": refresh_token,
                "token_type": "bearer",
            }
            # Dispatch CLIENTNEW event (sends welcome email with password)
            try:
                from packages.services.events import event_dispatcher
                await event_dispatcher.dispatch("client_event", {
                    "event_name": "CLIENTNEW",
                    "context": {
                        "EMAIL": body.customer_email,
                        "ORDER_USER": body.customer_name,
                        "PHONE": body.customer_phone or "",
                        "CLIENTPASSWORD": generated_password,
                        "CLIENTREGISTER_DATE": datetime.now(UTC).strftime("%d.%m.%Y %H:%M"),
                        "SERVER_NAME": settings.server_name,
                        "SHOP_NAME": settings.shop_name,
                        "SALE_EMAIL": settings.sale_email,
                        "SYS_SHOP_EMAIL": settings.smtp_from_email,
                    },
                })
            except Exception as exc:
                logger.warning("clientnew_event_failed", error=str(exc))
        except Exception as exc:
            logger.error("checkout_account_creation_failed", email=body.customer_email, error=str(exc))

    await db.commit()

    return {
        "ok": True,
        "data": {
            "order_number": order.order_number,
            "status": order.status,
            "order_type": order.order_type,
            "total": order.total / 100,
            "payment_method": order.payment_method,
            "public_token": order.guest_order_token,
            "guest_order_token": order.guest_order_token,
            "confirmation_url": confirmation_url,
            "auth_tokens": auth_tokens,
        },
        "request_id": request_id,
    }


# ---------------------------------------------------------------------------
# Create order (user)
# ---------------------------------------------------------------------------


@router.post("/me/checkout/create-order")
async def create_user_order(
    body: CreateOrderRequest,
    user_id: CurrentUserId,
    db: DbSession,
    redis: Redis,
    request_id: RequestId,
):
    await check_rate_limit(redis, f"checkout:{user_id}", max_requests=5, window_seconds=60)

    items = [{"sku": i.sku, "quantity": i.quantity} for i in body.items]
    delivery_price_kopecks = int(body.delivery_price * 100) if body.delivery_price else 0

    order = await checkout_service.create_order(
        db,
        items=items,
        customer_email=body.customer_email,
        customer_phone=body.customer_phone,
        customer_name=body.customer_name,
        delivery_provider=body.delivery_provider,
        delivery_city=body.delivery_city,
        delivery_address=body.delivery_address,
        pickup_point_id=body.pickup_point_id,
        pickup_point_name=body.pickup_point_name,
        customer_delivery_price=delivery_price_kopecks,
        carrier_estimated_cost=None,
        payment_method=body.payment_method,
        user_id=user_id,
        idempotency_key=body.idempotency_key,
    )

    # Auto-create YooKassa payment for card orders
    confirmation_url = None
    if body.payment_method == PaymentMethod.CARD:
        confirmation_url = await _create_yookassa_payment(db, order, request_id)

    await db.commit()

    return {
        "ok": True,
        "data": {
            "order_number": order.order_number,
            "status": order.status,
            "order_type": order.order_type,
            "total": order.total / 100,
            "payment_method": order.payment_method,
            "public_token": order.guest_order_token,
            "confirmation_url": confirmation_url,
        },
        "request_id": request_id,
    }
