from __future__ import annotations

import secrets
import string
from datetime import UTC, datetime
from typing import Optional

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, Query
from pydantic import BaseModel
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from apps.api.deps import DbSession, RequestId, require_admin
from packages.core.config import settings
from packages.core.exceptions import NotFoundError, ValidationError
from packages.core.security import hash_password
from packages.enums import OrderStatus
from packages.models.order import Order, OrderEvent, OrderItem
from packages.models.user import RefreshToken, User, UserProfile
from packages.services import auth as auth_service
from packages.services import checkout as checkout_service
from packages.services import delivery as delivery_service
from packages.integrations.magnit.client import get_client as get_magnit_client
from packages.services.order_state_machine import get_allowed_transitions, get_status_label, require_valid_transition

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


@router.get("/orders/{order_number}")
async def get_order(order_number: str, db: DbSession, request_id: RequestId):
    order = await checkout_service.get_order_by_number(db, order_number)
    if not order:
        raise NotFoundError("Order", order_number)

    return {
        "ok": True,
        "data": {
            "order_number": order.order_number,
            "status": order.status,
            "status_label": get_status_label(order.status),
            "order_type": order.order_type,
            "public_token": order.guest_order_token,
            "user_id": order.user_id,
            "guest_session_id": order.guest_session_id,
            "customer_email": order.customer_email,
            "customer_phone": order.customer_phone,
            "customer_name": order.customer_name,
            "delivery_provider": order.delivery_provider,
            "delivery_city": order.delivery_city,
            "pickup_point_id": order.pickup_point_id,
            "pickup_point_name": order.pickup_point_name,
            "payment_method": order.payment_method,
            "order_type": order.order_type,
            "subtotal": order.subtotal / 100,
            "discount_amount": order.discount_amount / 100,
            "customer_delivery_price": order.customer_delivery_price / 100,
            "carrier_estimated_cost": (order.carrier_estimated_cost or 0) / 100,
            "carrier_actual_cost": (order.carrier_actual_cost or 0) / 100,
            "total": order.total / 100,
            "items": [
                {
                    "product_sku": i.product_sku,
                    "product_name": i.product_name,
                    "quantity": i.quantity,
                    "unit_price": i.unit_price / 100,
                    "total_price": i.total_price / 100,
                    "weight_grams": i.weight_grams,
                    "vat_rate": i.vat_rate,
                }
                for i in order.items
            ],
            "events": [
                {
                    "event_type": e.event_type,
                    "old_status": e.old_status,
                    "new_status": e.new_status,
                    "data": e.data,
                    "created_at": e.created_at.isoformat() if e.created_at else None,
                }
                for e in order.events
            ],
            "created_at": order.created_at.isoformat() if order.created_at else None,
            "allowed_transitions": sorted(get_allowed_transitions(order.order_type, order.status)),
        },
        "request_id": request_id,
    }


@router.post("/orders/{order_number}/create-shipment")
async def create_order_shipment(
    order_number: str,
    db: DbSession,
    request_id: RequestId,
):
    """Create a shipment at the delivery provider for this order.

    The order must be in CONFIRMED (or later) status and must not already
    have a shipment.
    """
    from sqlalchemy import select as sa_select

    from packages.models.shipment import Shipment
    from packages.services.shipments import create_shipment

    order = await checkout_service.get_order_by_number(db, order_number)
    if not order:
        raise NotFoundError("Order", order_number)

    # Must be at least CONFIRMED
    allowed_for_shipment = {"confirmed", "shipped", "ready_for_pickup"}
    if order.status not in allowed_for_shipment:
        raise ValidationError(
            f"Cannot create shipment for order in status '{order.status}'. "
            f"Order must be in one of: {', '.join(sorted(allowed_for_shipment))}"
        )

    # Check for existing shipment
    existing_stmt = sa_select(Shipment).where(Shipment.order_id == order.id)
    existing_result = await db.execute(existing_stmt)
    existing_shipment = existing_result.scalar_one_or_none()
    if existing_shipment:
        raise ValidationError(
            f"Shipment already exists for order {order_number} "
            f"(provider_id={existing_shipment.provider_shipment_id})"
        )

    shipment = await create_shipment(db, order)
    await db.commit()

    return {
        "ok": True,
        "data": {
            "shipment_id": shipment.id,
            "provider": shipment.provider,
            "provider_shipment_id": shipment.provider_shipment_id,
            "provider_order_number": shipment.provider_order_number,
            "status": shipment.status,
            "parcel_size": shipment.parcel_size,
            "weight_grams": shipment.weight_grams,
        },
        "request_id": request_id,
    }


@router.get("/orders/{order_number}/shipment")
async def get_order_shipment(
    order_number: str,
    db: DbSession,
    request_id: RequestId,
):
    """Get shipment details for an order."""
    from sqlalchemy import select as sa_select

    from packages.models.shipment import Shipment

    order = await checkout_service.get_order_by_number(db, order_number)
    if not order:
        raise NotFoundError("Order", order_number)

    stmt = sa_select(Shipment).where(Shipment.order_id == order.id)
    result = await db.execute(stmt)
    shipment = result.scalar_one_or_none()

    if not shipment:
        return {"ok": True, "data": None, "request_id": request_id}

    return {
        "ok": True,
        "data": {
            "shipment_id": shipment.id,
            "provider": shipment.provider,
            "provider_shipment_id": shipment.provider_shipment_id,
            "provider_order_number": shipment.provider_order_number,
            "status": shipment.status,
            "tracking_number": shipment.tracking_number,
            "parcel_size": shipment.parcel_size,
            "weight_grams": shipment.weight_grams,
            "label_url": shipment.label_url,
            "created_at": shipment.created_at.isoformat() if shipment.created_at else None,
        },
        "request_id": request_id,
    }


@router.get("/orders/{order_number}/labels")
async def get_labels(order_number: str, db: DbSession, request_id: RequestId):
    """Download shipping label for an order's shipment."""
    from sqlalchemy import select as sa_select

    from packages.models.shipment import Shipment

    order = await checkout_service.get_order_by_number(db, order_number)
    if not order:
        raise NotFoundError("Order", order_number)

    stmt = sa_select(Shipment).where(Shipment.order_id == order.id)
    result = await db.execute(stmt)
    shipment = result.scalar_one_or_none()

    if not shipment or not shipment.provider_shipment_id:
        return {"ok": True, "data": {"labels": []}, "request_id": request_id}

    labels = []
    if shipment.provider == "magnit" and shipment.provider_shipment_id:
        try:
            client = get_magnit_client()
            label_bytes = await client.get_label(shipment.provider_shipment_id)
            import base64
            labels.append({
                "provider": "magnit",
                "format": "pdf",
                "data_base64": base64.b64encode(label_bytes).decode(),
            })
        except Exception as exc:
            logger.warning("label_fetch_failed", provider="magnit", error=str(exc))

    return {"ok": True, "data": {"labels": labels}, "request_id": request_id}


@router.post("/jobs/sync-5post-points")
async def sync_5post(request_id: RequestId, background_tasks: BackgroundTasks):
    from apps.worker.jobs.sync_5post_points import sync_fivepost_points

    background_tasks.add_task(sync_fivepost_points)
    return {
        "ok": True,
        "data": {"job_name": "sync_5post_points", "status": "triggered"},
        "request_id": request_id,
    }


@router.post("/jobs/sync-magnit-points")
async def sync_magnit(request_id: RequestId, background_tasks: BackgroundTasks):
    from apps.worker.jobs.sync_magnit_points import sync_magnit_points

    background_tasks.add_task(sync_magnit_points)
    return {
        "ok": True,
        "data": {"job_name": "sync_magnit_points", "status": "triggered"},
        "request_id": request_id,
    }


@router.post("/jobs/poll-magnit-statuses")
async def poll_magnit(request_id: RequestId):
    return {
        "ok": True,
        "data": {"job_name": "poll_magnit_statuses", "status": "triggered"},
        "request_id": request_id,
    }


@router.post("/orders/{order_number}/refresh-provider-state")
async def refresh_provider(order_number: str, db: DbSession, request_id: RequestId):
    order = await checkout_service.get_order_by_number(db, order_number)
    if not order:
        raise NotFoundError("Order", order_number)
    # TODO: fetch latest from provider
    return {"ok": True, "data": {"message": "Provider state refreshed"}, "request_id": request_id}


@router.get("/provider-events")
async def list_provider_events(db: DbSession, request_id: RequestId):
    from sqlalchemy import select

    from packages.models.provider import ProviderWebhookEvent

    stmt = select(ProviderWebhookEvent).order_by(ProviderWebhookEvent.received_at.desc()).limit(100)
    result = await db.execute(stmt)
    events = result.scalars().all()
    return {
        "ok": True,
        "data": [
            {
                "id": e.id,
                "provider": e.provider,
                "event_type": e.event_type,
                "external_id": e.external_id,
                "processed": e.processed,
                "received_at": e.received_at.isoformat() if e.received_at else None,
            }
            for e in events
        ],
        "request_id": request_id,
    }


@router.get("/pickup-points/cache-status")
async def cache_status(db: DbSession, request_id: RequestId):
    fivepost = await delivery_service.get_cache_status(db, "5post")
    magnit = await delivery_service.get_cache_status(db, "magnit")
    return {"ok": True, "data": [fivepost, magnit], "request_id": request_id}


# ---------------------------------------------------------------------------
# Pydantic request bodies
# ---------------------------------------------------------------------------


class SetStatusBody(BaseModel):
    new_status: str


class CreateClientBody(BaseModel):
    email: str
    password: str
    phone: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None


class ResetPasswordBody(BaseModel):
    new_password: Optional[str] = None


# ---------------------------------------------------------------------------
# Order Management Endpoints
# ---------------------------------------------------------------------------


@router.get("/orders")
async def list_orders(
    db: DbSession,
    request_id: RequestId,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    status: Optional[str] = Query(None),
    order_type: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
):
    """Paginated list of all orders."""
    # Base query for counting
    count_stmt = select(func.count(Order.id))
    # Base query for fetching
    list_stmt = select(Order).options(selectinload(Order.items))

    # Apply filters
    if status:
        count_stmt = count_stmt.where(Order.status == status)
        list_stmt = list_stmt.where(Order.status == status)
    if order_type:
        count_stmt = count_stmt.where(Order.order_type == order_type)
        list_stmt = list_stmt.where(Order.order_type == order_type)
    if search:
        search_filter = or_(
            Order.order_number.ilike(f"%{search}%"),
            Order.customer_email.ilike(f"%{search}%"),
            Order.customer_phone.ilike(f"%{search}%"),
        )
        count_stmt = count_stmt.where(search_filter)
        list_stmt = list_stmt.where(search_filter)

    # Total count
    total_result = await db.execute(count_stmt)
    total = total_result.scalar()

    # Paginated list
    offset = (page - 1) * per_page
    list_stmt = list_stmt.order_by(Order.created_at.desc()).offset(offset).limit(per_page)
    result = await db.execute(list_stmt)
    orders = result.scalars().all()

    return {
        "ok": True,
        "data": {
            "orders": [
                {
                    "order_number": o.order_number,
                    "order_type": o.order_type,
                    "status": o.status,
                    "status_label": get_status_label(o.status),
                    "delivery_provider": o.delivery_provider,
                    "payment_method": o.payment_method,
                    "public_token": o.guest_order_token,
                    "customer_name": o.customer_name,
                    "customer_email": o.customer_email,
                    "total": o.total / 100,
                    "items_count": len(o.items),
                    "created_at": o.created_at.isoformat() if o.created_at else None,
                }
                for o in orders
            ],
            "total": total,
            "page": page,
            "per_page": per_page,
        },
        "request_id": request_id,
    }


@router.post("/orders/{order_number}/set-status")
async def set_order_status(
    order_number: str,
    body: SetStatusBody,
    db: DbSession,
    request_id: RequestId,
):
    """Change order status using the state machine."""
    order = await checkout_service.get_order_by_number(db, order_number)
    if not order:
        raise NotFoundError("Order", order_number)

    new_status = body.new_status
    require_valid_transition(order.order_type, order.status, new_status)

    updated_order = await checkout_service.update_order_status(
        db, order, new_status, event_data={"source": "admin"}
    )
    await db.commit()

    return {
        "ok": True,
        "data": {
            "order_number": updated_order.order_number,
            "old_status": order.status if order.status != updated_order.status else None,
            "status": updated_order.status,
            "status_label": get_status_label(updated_order.status),
            "allowed_transitions": sorted(get_allowed_transitions(updated_order.order_type, updated_order.status)),
        },
        "request_id": request_id,
    }


@router.delete("/orders/{order_number}")
async def delete_order(
    order_number: str,
    db: DbSession,
    request_id: RequestId,
):
    """Hard delete an order with all items and events."""
    order = await checkout_service.get_order_by_number(db, order_number)
    if not order:
        raise NotFoundError("Order", order_number)

    # Delete events, items, then order (CASCADE should handle it, but be explicit)
    await db.execute(delete(OrderEvent).where(OrderEvent.order_id == order.id))
    await db.execute(delete(OrderItem).where(OrderItem.order_id == order.id))
    await db.execute(delete(Order).where(Order.id == order.id))
    await db.commit()

    return {
        "ok": True,
        "data": {"message": f"Order {order_number} deleted"},
        "request_id": request_id,
    }


# ---------------------------------------------------------------------------
# Client Management Endpoints
# ---------------------------------------------------------------------------


def _generate_random_password(length: int = 8) -> str:
    alphabet = string.ascii_lowercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


async def _get_client_orders_stats(db: AsyncSession, user_id: str) -> tuple[int, int]:
    """Return (orders_count, total_spent_kopecks) for a user.

    total_spent is sum of totals for DELIVERED orders only.
    """
    count_stmt = select(func.count(Order.id)).where(Order.user_id == user_id)
    count_result = await db.execute(count_stmt)
    orders_count = count_result.scalar() or 0

    spent_stmt = select(func.coalesce(func.sum(Order.total), 0)).where(
        Order.user_id == user_id,
        Order.status == OrderStatus.DELIVERED,
    )
    spent_result = await db.execute(spent_stmt)
    total_spent = spent_result.scalar() or 0

    return orders_count, total_spent


@router.get("/clients")
async def list_clients(
    db: DbSession,
    request_id: RequestId,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    search: Optional[str] = Query(None),
):
    """Paginated list of clients."""
    count_stmt = select(func.count(User.id))
    list_stmt = select(User).options(selectinload(User.profile))

    if search:
        search_filter = or_(
            User.email.ilike(f"%{search}%"),
            User.phone.ilike(f"%{search}%"),
        )
        # Also search in profile display_name via a subquery
        profile_match = select(UserProfile.user_id).where(
            UserProfile.display_name.ilike(f"%{search}%")
        ).scalar_subquery()
        combined_filter = or_(search_filter, User.id.in_(profile_match))
        count_stmt = count_stmt.where(combined_filter)
        list_stmt = list_stmt.where(combined_filter)

    total_result = await db.execute(count_stmt)
    total = total_result.scalar()

    offset = (page - 1) * per_page
    list_stmt = list_stmt.order_by(User.created_at.desc()).offset(offset).limit(per_page)
    result = await db.execute(list_stmt)
    users = result.scalars().all()

    clients = []
    for u in users:
        orders_count, total_spent = await _get_client_orders_stats(db, u.id)
        clients.append({
            "id": u.id,
            "email": u.email,
            "phone": u.phone,
            "display_name": u.profile.display_name if u.profile else None,
            "plain_password": u.plain_password,
            "created_at": u.created_at.isoformat() if u.created_at else None,
            "orders_count": orders_count,
            "total_spent": total_spent / 100,
        })

    return {
        "ok": True,
        "data": {
            "clients": clients,
            "total": total,
            "page": page,
            "per_page": per_page,
        },
        "request_id": request_id,
    }


@router.get("/clients/{user_id}")
async def get_client(
    user_id: str,
    db: DbSession,
    request_id: RequestId,
):
    """Client detail with all their orders."""
    stmt = select(User).where(User.id == user_id).options(selectinload(User.profile))
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    if not user:
        raise NotFoundError("Client", user_id)

    # Fetch user's orders
    orders_stmt = (
        select(Order)
        .where(Order.user_id == user_id)
        .options(selectinload(Order.items))
        .order_by(Order.created_at.desc())
    )
    orders_result = await db.execute(orders_stmt)
    orders = orders_result.scalars().all()

    orders_count, total_spent = await _get_client_orders_stats(db, user_id)

    return {
        "ok": True,
        "data": {
            "id": user.id,
            "email": user.email,
            "phone": user.phone,
            "display_name": user.profile.display_name if user.profile else None,
            "first_name": user.profile.first_name if user.profile else None,
            "last_name": user.profile.last_name if user.profile else None,
            "plain_password": user.plain_password,
            "is_active": user.is_active,
            "created_at": user.created_at.isoformat() if user.created_at else None,
            "orders_count": orders_count,
            "total_spent": total_spent / 100,
            "orders": [
                {
                    "order_number": o.order_number,
                    "order_type": o.order_type,
                    "status": o.status,
                    "status_label": get_status_label(o.status),
                    "total": o.total / 100,
                    "items_count": len(o.items),
                    "created_at": o.created_at.isoformat() if o.created_at else None,
                }
                for o in orders
            ],
        },
        "request_id": request_id,
    }


@router.post("/clients")
async def create_client(
    body: CreateClientBody,
    db: DbSession,
    request_id: RequestId,
):
    """Create a new client (user) and link existing orders by email."""
    user, access_token, _ = await auth_service.register_user(
        db,
        email=body.email,
        password=body.password,
        phone=body.phone,
        first_name=body.first_name,
        last_name=body.last_name,
    )

    # Link any existing orders with the same email to this user
    link_stmt = (
        select(Order)
        .where(Order.customer_email == user.email, Order.user_id.is_(None))
    )
    link_result = await db.execute(link_stmt)
    unlinked_orders = link_result.scalars().all()
    linked_count = 0
    for order in unlinked_orders:
        order.user_id = user.id
        linked_count += 1

    # Dispatch CLIENTNEW event for email notification
    try:
        from packages.services.events import event_dispatcher
        await event_dispatcher.dispatch("client_event", {
            "event_name": "CLIENTNEW",
            "context": {
                "EMAIL": user.email,
                "ORDER_USER": f"{body.last_name or ''} {body.first_name or ''}".strip(),
                "PHONE": user.phone or "",
                "CLIENTPASSWORD": body.password,
                "CLIENTREGISTER_DATE": datetime.now(UTC).strftime("%d.%m.%Y %H:%M"),
                "SERVER_NAME": settings.server_name,
                "SHOP_NAME": settings.shop_name,
                "SALE_EMAIL": settings.sale_email,
                "SYS_SHOP_EMAIL": settings.smtp_from_email,
            },
        })
    except Exception as exc:
        logger.warning("event_dispatch_failed", event="CLIENTNEW", error=str(exc))

    await db.commit()

    return {
        "ok": True,
        "data": {
            "id": user.id,
            "email": user.email,
            "phone": user.phone,
            "linked_orders": linked_count,
        },
        "request_id": request_id,
    }


@router.post("/clients/{user_id}/reset-password")
async def reset_client_password(
    user_id: str,
    body: ResetPasswordBody,
    db: DbSession,
    request_id: RequestId,
):
    """Reset client password. If new_password not provided, generates random 8-char one."""
    from sqlalchemy.orm import selectinload
    stmt = select(User).options(selectinload(User.profile)).where(User.id == user_id)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    if not user:
        raise NotFoundError("Client", user_id)

    new_password = body.new_password or _generate_random_password()
    user.password_hash = hash_password(new_password)
    user.plain_password = new_password

    user_name = user.email
    if user.profile:
        user_name = f"{user.profile.last_name or ''} {user.profile.first_name or ''}".strip() or user.email

    # Dispatch CLIENTRESETPASS event for email notification
    try:
        from packages.services.events import event_dispatcher
        await event_dispatcher.dispatch("client_event", {
            "event_name": "CLIENTRESETPASS",
            "context": {
                "EMAIL": user.email,
                "ORDER_USER": user_name,
                "CLIENTPASSWORD": new_password,
                "SERVER_NAME": settings.server_name,
                "SHOP_NAME": settings.shop_name,
                "SALE_EMAIL": settings.sale_email,
                "SYS_SHOP_EMAIL": settings.smtp_from_email,
            },
        })
    except Exception as exc:
        logger.warning("event_dispatch_failed", event="CLIENTRESETPASS", error=str(exc))

    await db.commit()

    return {
        "ok": True,
        "data": {
            "user_id": user.id,
            "email": user.email,
            "new_password": new_password,
        },
        "request_id": request_id,
    }


@router.delete("/clients/{user_id}")
async def delete_client(
    user_id: str,
    db: DbSession,
    request_id: RequestId,
    delete_orders: bool = Query(False),
):
    """Delete a client. Optionally delete their orders too."""
    stmt = select(User).where(User.id == user_id)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    if not user:
        raise NotFoundError("Client", user_id)

    if delete_orders:
        # Find all orders belonging to this user
        orders_stmt = select(Order).where(Order.user_id == user_id)
        orders_result = await db.execute(orders_stmt)
        user_orders = orders_result.scalars().all()
        for order in user_orders:
            await db.execute(delete(OrderEvent).where(OrderEvent.order_id == order.id))
            await db.execute(delete(OrderItem).where(OrderItem.order_id == order.id))
            await db.execute(delete(Order).where(Order.id == order.id))
    else:
        # Unlink orders (set user_id to None)
        orders_stmt = select(Order).where(Order.user_id == user_id)
        orders_result = await db.execute(orders_stmt)
        user_orders = orders_result.scalars().all()
        for order in user_orders:
            order.user_id = None

    # Delete refresh tokens, profile, then user
    await db.execute(delete(RefreshToken).where(RefreshToken.user_id == user_id))
    await db.execute(delete(UserProfile).where(UserProfile.user_id == user_id))
    await db.execute(delete(User).where(User.id == user_id))
    await db.commit()

    return {
        "ok": True,
        "data": {"message": f"Client {user.email} deleted"},
        "request_id": request_id,
    }


# ── Test email ──

class TestEmailRequest(BaseModel):
    to: str


@router.post("/test-email")
async def send_test_email(body: TestEmailRequest, request_id: RequestId):
    """Send a test email to verify SMTP configuration."""
    import json
    import time
    import uuid

    from packages.core.redis import get_redis

    to = body.to
    subject = f"[VKUS Online] Тестовое письмо"
    html_body = (
        '<h2 style="margin:0 0 16px;font-size:20px;font-weight:600;color:#333;">Тестовое письмо</h2>'
        f'<p style="margin:0 0 12px;color:#555;font-size:15px;">Это тестовое письмо от <strong>{settings.shop_name}</strong>.</p>'
        f'<p style="margin:0 0 8px;color:#555;font-size:14px;">SMTP: <code>{settings.smtp_host}:{settings.smtp_port}</code></p>'
        f'<p style="margin:0 0 8px;color:#555;font-size:14px;">От: <code>{settings.smtp_from_email}</code></p>'
        f'<p style="margin:0 0 8px;color:#555;font-size:14px;">Кому: <code>{to}</code></p>'
        f'<p style="margin:0;color:#888;font-size:13px;">Отправлено: {datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")}</p>'
    )

    redis = await get_redis()
    msg_id = str(uuid.uuid4())
    payload = json.dumps({
        "msg_id": msg_id,
        "to": to,
        "subject": subject,
        "body": html_body,
        "from_addr": settings.smtp_from_email,
        "_retries": 0,
        "_created_at": time.time(),
    })
    await redis.hset("email:msgs", msg_id, payload)
    await redis.zadd("email:pending", {msg_id: time.time()})

    logger.info("test_email_queued", to=to, msg_id=msg_id)

    return {
        "ok": True,
        "data": {
            "message": f"Test email queued to {to}",
            "msg_id": msg_id,
            "from": settings.smtp_from_email,
            "smtp": f"{settings.smtp_host}:{settings.smtp_port}",
        },
        "request_id": request_id,
    }
