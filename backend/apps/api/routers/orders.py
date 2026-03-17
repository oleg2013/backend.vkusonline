from __future__ import annotations

from fastapi import APIRouter

from apps.api.deps import CurrentUserId, DbSession, GuestSessionId, RequestId
from packages.core.exceptions import NotFoundError
from packages.services import checkout as checkout_service
from packages.services import orders as orders_service
from packages.services import guests as guest_service

router = APIRouter(tags=["orders"])


def _order_response(order, request_id):
    return {
        "ok": True,
        "data": {
            "order_number": order.order_number,
            "status": order.status,
            "customer_name": order.customer_name,
            "customer_email": order.customer_email,
            "delivery_provider": order.delivery_provider,
            "delivery_city": order.delivery_city,
            "pickup_point_id": order.pickup_point_id,
            "pickup_point_name": order.pickup_point_name,
            "subtotal": order.subtotal / 100,
            "discount_amount": order.discount_amount / 100,
            "delivery_price": order.customer_delivery_price / 100,
            "total": order.total / 100,
            "items": [
                {
                    "product_sku": i.product_sku,
                    "product_name": i.product_name,
                    "quantity": i.quantity,
                    "unit_price": i.unit_price / 100,
                    "total_price": i.total_price / 100,
                }
                for i in order.items
            ],
            "created_at": order.created_at.isoformat() if order.created_at else None,
            "guest_order_token": order.guest_order_token,
        },
        "request_id": request_id,
    }


# === Guest Orders ===

@router.get("/guest/orders/{order_number}")
async def get_guest_order(
    order_number: str,
    guest_session_id: GuestSessionId,
    db: DbSession,
    request_id: RequestId,
):
    await guest_service.validate_guest_session(db, guest_session_id)
    order = await orders_service.get_guest_order(db, order_number, guest_session_id)
    return _order_response(order, request_id)


@router.get("/guest/orders/{order_number}/status")
async def get_guest_order_status(
    order_number: str,
    guest_session_id: GuestSessionId,
    db: DbSession,
    request_id: RequestId,
):
    await guest_service.validate_guest_session(db, guest_session_id)
    order = await orders_service.get_guest_order(db, order_number, guest_session_id)
    return {
        "ok": True,
        "data": {
            "order_number": order.order_number,
            "status": order.status,
            "payment_status": None,  # TODO: fetch from payments
            "shipment_status": None,  # TODO: fetch from shipments
        },
        "request_id": request_id,
    }


@router.post("/guest/orders/{order_number}/cancel")
async def cancel_guest_order(
    order_number: str,
    guest_session_id: GuestSessionId,
    db: DbSession,
    request_id: RequestId,
):
    await guest_service.validate_guest_session(db, guest_session_id)
    order = await orders_service.get_guest_order(db, order_number, guest_session_id)
    order = await checkout_service.cancel_order(db, order)
    return {
        "ok": True,
        "data": {"order_number": order.order_number, "status": order.status},
        "request_id": request_id,
    }


@router.post("/guest/orders/{order_number}/retry-payment")
async def retry_guest_payment(
    order_number: str,
    guest_session_id: GuestSessionId,
    db: DbSession,
    request_id: RequestId,
):
    await guest_service.validate_guest_session(db, guest_session_id)
    order = await orders_service.get_guest_order(db, order_number, guest_session_id)
    # TODO: implement payment retry
    return {
        "ok": True,
        "data": {"order_number": order.order_number, "message": "Payment retry initiated"},
        "request_id": request_id,
    }


# === User Orders ===

@router.get("/me/orders")
async def list_user_orders(
    user_id: CurrentUserId,
    db: DbSession,
    request_id: RequestId,
    page: int = 1,
    per_page: int = 20,
):
    orders, total = await orders_service.get_user_orders(db, user_id, page, per_page)
    return {
        "ok": True,
        "data": {
            "items": [
                {
                    "order_number": o.order_number,
                    "status": o.status,
                    "total": o.total / 100,
                    "created_at": o.created_at.isoformat() if o.created_at else None,
                    "items_count": len(o.items),
                    "payment_method": o.payment_method,
                }
                for o in orders
            ],
            "total": total,
            "page": page,
            "per_page": per_page,
        },
        "request_id": request_id,
    }


@router.get("/me/orders/{order_number}")
async def get_user_order(
    order_number: str,
    user_id: CurrentUserId,
    db: DbSession,
    request_id: RequestId,
):
    order = await orders_service.get_user_order(db, order_number, user_id)
    return _order_response(order, request_id)


@router.get("/me/orders/{order_number}/status")
async def get_user_order_status(
    order_number: str,
    user_id: CurrentUserId,
    db: DbSession,
    request_id: RequestId,
):
    order = await orders_service.get_user_order(db, order_number, user_id)
    return {
        "ok": True,
        "data": {
            "order_number": order.order_number,
            "status": order.status,
            "payment_status": None,
            "shipment_status": None,
        },
        "request_id": request_id,
    }


@router.post("/me/orders/{order_number}/cancel")
async def cancel_user_order(
    order_number: str,
    user_id: CurrentUserId,
    db: DbSession,
    request_id: RequestId,
):
    order = await orders_service.get_user_order(db, order_number, user_id)
    order = await checkout_service.cancel_order(db, order)
    return {
        "ok": True,
        "data": {"order_number": order.order_number, "status": order.status},
        "request_id": request_id,
    }


@router.post("/me/orders/{order_number}/retry-payment")
async def retry_user_payment(
    order_number: str,
    user_id: CurrentUserId,
    db: DbSession,
    request_id: RequestId,
):
    order = await orders_service.get_user_order(db, order_number, user_id)
    return {
        "ok": True,
        "data": {"order_number": order.order_number, "message": "Payment retry initiated"},
        "request_id": request_id,
    }
