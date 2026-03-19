from __future__ import annotations

from fastapi import APIRouter

from apps.api.deps import CurrentUserId, DbSession, GuestSessionId, Redis, RequestId
from packages.core.config import settings
from packages.core.exceptions import NotFoundError
from packages.core.rate_limit import check_rate_limit
from packages.enums import PaymentStatus
from packages.integrations.yookassa.client import YooKassaClient
from packages.integrations.yookassa.receipt_builder import build_receipt
from packages.schemas.payment import PaymentCreateRequest
from packages.services import checkout as checkout_service
from packages.services import orders as orders_service
from packages.services import guests as guest_service
from packages.services import payments as payment_service

router = APIRouter(tags=["payments"])

yookassa_client = YooKassaClient(
    shop_id=settings.yookassa_shop_id,
    secret_key=settings.yookassa_secret_key,
)


async def _create_payment_for_order(db, order, idempotency_key, request_id):
    payment = await payment_service.create_payment(db, order, idempotency_key)

    # Build receipt
    receipt = build_receipt(
        items=[
            {
                "name": item.product_name,
                "quantity": item.quantity,
                "unit_price_kopecks": item.unit_price,
                "vat_rate": item.vat_rate,
            }
            for item in order.items
        ],
        customer_email=order.customer_email,
        customer_phone=order.customer_phone,
        customer_name=order.customer_name,
    )

    # Create payment at YooKassa (amount in rubles)
    provider_result = await yookassa_client.create_payment(
        amount_rub=order.total / 100,
        receipt=receipt,
        return_url=settings.effective_yookassa_return_url,
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

    return {
        "ok": True,
        "data": {
            "payment_id": payment.id,
            "confirmation_url": payment.confirmation_url,
            "status": payment.status,
        },
        "request_id": request_id,
    }


@router.post("/guest/orders/{order_number}/payments/yookassa/create")
async def create_guest_payment(
    order_number: str,
    body: PaymentCreateRequest,
    guest_session_id: GuestSessionId,
    db: DbSession,
    redis: Redis,
    request_id: RequestId,
):
    await check_rate_limit(redis, f"payment:{guest_session_id}", max_requests=5, window_seconds=60)
    await guest_service.validate_guest_session(db, guest_session_id)
    order = await orders_service.get_guest_order(db, order_number, guest_session_id)
    return await _create_payment_for_order(db, order, body.idempotency_key, request_id)


@router.post("/me/orders/{order_number}/payments/yookassa/create")
async def create_user_payment(
    order_number: str,
    body: PaymentCreateRequest,
    user_id: CurrentUserId,
    db: DbSession,
    redis: Redis,
    request_id: RequestId,
):
    await check_rate_limit(redis, f"payment:{user_id}", max_requests=5, window_seconds=60)
    order = await orders_service.get_user_order(db, order_number, user_id)
    return await _create_payment_for_order(db, order, body.idempotency_key, request_id)
