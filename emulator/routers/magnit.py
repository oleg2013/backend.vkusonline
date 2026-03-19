"""Magnit Post API emulator endpoints.

Implements the subset of Magnit API that our backend client actually calls:
- POST /api/v2/oauth/token                      — OAuth token
- POST /api/v2/magnit-post/orders                — create order
- GET  /api/v2/magnit-post/orders/{id}           — get order status
- DELETE /api/v1/magnit-post/orders/{id}         — cancel order
- GET  /api/v1/magnit-post/orders/{id}/label     — get label (stub PDF)
- GET  /api/v1/magnit-post/orders/{id}/status-history — status history
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import EmulMagnitOrder, EmulMagnitStatusHistory, get_db

router = APIRouter()
log = logging.getLogger("emulator.magnit")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _ts_ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


# ── OAuth token (stub) ──────────────────────────────────────────────

@router.post("/api/v2/oauth/token")
async def oauth_token(request: Request):
    """Return a dummy OAuth2 access token. Accepts any credentials."""
    import base64, json, time

    form = await request.form()
    client_id = form.get("client_id", "unknown")
    log.info("[MAGNIT] OAuth requested  client_id=%s  ip=%s", client_id, request.client.host if request.client else "-")

    header = base64.urlsafe_b64encode(json.dumps({"alg": "RS256", "typ": "JWT"}).encode()).decode().rstrip("=")
    payload = base64.urlsafe_b64encode(json.dumps({
        "sub": "emulator",
        "exp": int(time.time()) + 3600,
        "iat": int(time.time()),
        "scope": "openid",
    }).encode()).decode().rstrip("=")
    signature = base64.urlsafe_b64encode(b"magnit-emulator-stub").decode().rstrip("=")

    log.info("[MAGNIT] OAuth token issued  client_id=%s  expires_in=3600", client_id)
    return {
        "access_token": f"{header}.{payload}.{signature}",
        "expires_in": 3600,
        "scope": "openid",
        "token_type": "bearer",
    }


# ── Create order ────────────────────────────────────────────────────

@router.post("/api/v2/magnit-post/orders", status_code=201)
async def create_order(request: Request, db: AsyncSession = Depends(get_db)):
    """Create an order — emulates POST /api/v2/magnit-post/orders."""
    body = await request.json()

    customer_order_id = body.get("customer_order_id", "")
    pickup_point = body.get("pickup_point", {})
    recipient = body.get("recipient", {})
    parcels = body.get("parcels", [{}])
    first_parcel = parcels[0] if parcels else {}
    billing_type = first_parcel.get("parcel_payment", {}).get("billing_type", "unknown")

    log.info("[MAGNIT] Create order  customer_order_id=%s  pvz=%s  billing=%s  ip=%s",
             customer_order_id, pickup_point.get("key", "-"), billing_type,
             request.client.host if request.client else "-")

    tracking_number = uuid.uuid4()
    parcel_id = uuid.uuid4()

    barcode = first_parcel.get("barcode") or f"MG{uuid.uuid4().hex[:12].upper()}"

    first_name = recipient.get("first_name", "")
    family_name = recipient.get("family_name", "")
    recipient_name = f"{first_name} {family_name}".strip()

    order = EmulMagnitOrder(
        tracking_number=tracking_number,
        customer_order_id=customer_order_id,
        external_order_id=body.get("external_order_id", ""),
        pickup_point_key=pickup_point.get("key", ""),
        recipient_phone=recipient.get("phone_number", ""),
        recipient_name=recipient_name,
        status="NEW",
        warehouse_id=body.get("warehouse_id", ""),
        return_type=body.get("return_type", "return"),
        order_data=body,
        parcel_id=parcel_id,
        parcel_barcode=barcode,
    )
    db.add(order)

    db.add(EmulMagnitStatusHistory(
        tracking_number=tracking_number,
        status="NEW",
        timestamp=_utcnow(),
    ))

    await db.flush()

    parcel_payment = first_parcel.get("parcel_payment", {})
    characteristic = first_parcel.get("characteristic", {})

    log.info("[MAGNIT] Order created  tracking=%s  customer_order_id=%s  recipient=%s  barcode=%s  status=NEW",
             tracking_number, customer_order_id, recipient_name, barcode)

    return {
        "tracking_number": str(tracking_number),
        "customer_order_id": customer_order_id,
        "external_order_id": body.get("external_order_id", ""),
        "recipient": recipient,
        "pickup_point": pickup_point,
        "warehouse_id": body.get("warehouse_id", ""),
        "return_type": body.get("return_type", "return"),
        "return_warehouse_id": body.get("return_warehouse_id", ""),
        "parcels": [{
            "id": str(parcel_id),
            "declared_value": first_parcel.get("declared_value", 0),
            "characteristic": characteristic,
            "parcel_payment": parcel_payment,
            "barcode": barcode,
            "status": "NEW",
        }],
    }


# ── Get order status ────────────────────────────────────────────────

@router.get("/api/v2/magnit-post/orders/{order_id}")
async def get_order_status(order_id: str, db: AsyncSession = Depends(get_db)):
    """Return full order details including current status."""
    log.info("[MAGNIT] Get status  order_id=%s", order_id)

    try:
        uid = uuid.UUID(order_id)
    except ValueError:
        log.warning("[MAGNIT] Invalid UUID  order_id=%s", order_id)
        return Response(
            content='{"code": "BAD_REQUEST", "message": "Invalid UUID"}',
            status_code=400,
            media_type="application/json",
        )

    result = await db.execute(
        select(EmulMagnitOrder).where(EmulMagnitOrder.tracking_number == uid)
    )
    order = result.scalar_one_or_none()
    if not order:
        log.warning("[MAGNIT] Order not found  order_id=%s", order_id)
        return Response(
            content='{"code": "NOT_FOUND", "message": "Order not found"}',
            status_code=404,
            media_type="application/json",
        )

    order_data = order.order_data or {}
    recipient = order_data.get("recipient", {})
    parcels_data = order_data.get("parcels", [{}])
    first_parcel = parcels_data[0] if parcels_data else {}

    log.info("[MAGNIT] Status response  tracking=%s  customer_order_id=%s  status=%s",
             order_id, order.customer_order_id, order.status)

    return {
        "tracking_number": str(order.tracking_number),
        "customer_order_id": order.customer_order_id or "",
        "external_order_id": order.external_order_id or "",
        "delivery": {
            "pickup_point_key": order.pickup_point_key or "",
            "pickup_point_address": "",
        },
        "recipient": recipient,
        "pickup_code": f"{hash(str(order.tracking_number)) % 10000:04d}",
        "tracking_link": f"https://magnit-emul-api.vkus.online/track/{order.tracking_number}",
        "full_tracking_link": f"https://magnit-emul-api.vkus.online/track/{order.tracking_number}",
        "created_at": _iso(order.created_at),
        "warehouse_id": order.warehouse_id or "",
        "return_type": order.return_type or "return",
        "return_warehouse_id": order_data.get("return_warehouse_id", ""),
        "status": order.status,
        "parcels": [{
            "id": str(order.parcel_id),
            "declared_value": first_parcel.get("declared_value", 0),
            "characteristic": first_parcel.get("characteristic", {}),
            "parcel_payment": first_parcel.get("parcel_payment", {}),
            "barcode": order.parcel_barcode or "",
            "status": order.status,
        }],
    }


# ── Cancel order ────────────────────────────────────────────────────

@router.delete("/api/v1/magnit-post/orders/{order_id}")
async def cancel_order(order_id: str, db: AsyncSession = Depends(get_db)):
    """Cancel an order (only in early statuses)."""
    log.info("[MAGNIT] Cancel request  order_id=%s", order_id)

    try:
        uid = uuid.UUID(order_id)
    except ValueError:
        log.warning("[MAGNIT] Cancel invalid UUID  order_id=%s", order_id)
        return Response(
            content='{"code": "BAD_REQUEST", "message": "Invalid UUID"}',
            status_code=400,
            media_type="application/json",
        )

    result = await db.execute(
        select(EmulMagnitOrder).where(EmulMagnitOrder.tracking_number == uid)
    )
    order = result.scalar_one_or_none()
    if not order:
        log.warning("[MAGNIT] Cancel: order not found  order_id=%s", order_id)
        return Response(
            content='{"code": "NOT_FOUND", "message": "Order not found"}',
            status_code=404,
            media_type="application/json",
        )

    if order.status not in ("NEW", "CREATED"):
        log.warning("[MAGNIT] Cancel: wrong status  order_id=%s  status=%s", order_id, order.status)
        return Response(
            content=f'{{"code": "UNPROCESSABLE_ENTITY", "message": "Cannot cancel order in status {order.status}"}}',
            status_code=422,
            media_type="application/json",
        )

    now = _utcnow()
    old_status = order.status
    order.status = "CANCELED_BY_PROVIDER"
    order.updated_at = now

    db.add(EmulMagnitStatusHistory(
        tracking_number=uid,
        status="CANCELED_BY_PROVIDER",
        timestamp=now,
    ))

    await db.flush()
    log.info("[MAGNIT] Order cancelled  tracking=%s  customer_order_id=%s  was=%s",
             order_id, order.customer_order_id, old_status)
    return Response(status_code=204)


# ── Status history ──────────────────────────────────────────────────

@router.get("/api/v1/magnit-post/orders/{order_id}/status-history")
async def get_status_history(order_id: str, db: AsyncSession = Depends(get_db)):
    """Return status history for an order."""
    log.info("[MAGNIT] Status history  order_id=%s", order_id)

    try:
        uid = uuid.UUID(order_id)
    except ValueError:
        log.warning("[MAGNIT] History invalid UUID  order_id=%s", order_id)
        return Response(
            content='{"code": "BAD_REQUEST", "message": "Invalid UUID"}',
            status_code=400,
            media_type="application/json",
        )

    result = await db.execute(
        select(EmulMagnitOrder).where(EmulMagnitOrder.tracking_number == uid)
    )
    if not result.scalar_one_or_none():
        log.warning("[MAGNIT] History: order not found  order_id=%s", order_id)
        return Response(
            content='{"code": "NOT_FOUND", "message": "Order not found"}',
            status_code=404,
            media_type="application/json",
        )

    hist_result = await db.execute(
        select(EmulMagnitStatusHistory)
        .where(EmulMagnitStatusHistory.tracking_number == uid)
        .order_by(EmulMagnitStatusHistory.timestamp)
    )
    rows = hist_result.scalars().all()

    log.info("[MAGNIT] History response  order_id=%s  entries=%d", order_id, len(rows))

    return {
        "trackingNumber": str(uid),
        "statuses": [
            {"status": h.status, "timestamp": _ts_ms(h.timestamp)}
            for h in rows
        ],
    }


# ── Get label (stub) ────────────────────────────────────────────────

@router.get("/api/v1/magnit-post/orders/{order_id}/label")
async def get_label(order_id: str, db: AsyncSession = Depends(get_db)):
    """Return a stub PDF label."""
    log.info("[MAGNIT] Label request  order_id=%s", order_id)

    try:
        uid = uuid.UUID(order_id)
    except ValueError:
        return Response(status_code=400, content=b"Invalid UUID")

    result = await db.execute(
        select(EmulMagnitOrder).where(EmulMagnitOrder.tracking_number == uid)
    )
    order = result.scalar_one_or_none()
    if not order:
        log.warning("[MAGNIT] Label: order not found  order_id=%s", order_id)
        return Response(status_code=404, content=b"Order not found")

    pdf_content = (
        b"%PDF-1.0\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R/Resources<<>>>>endobj\n"
        b"xref\n0 4\n0000000000 65535 f \n0000000009 00000 n \n"
        b"0000000058 00000 n \n0000000115 00000 n \n"
        b"trailer<</Size 4/Root 1 0 R>>\nstartxref\n229\n%%EOF"
    )
    log.info("[MAGNIT] Label served  tracking=%s  customer_order_id=%s  size=%d bytes",
             order_id, order.customer_order_id, len(pdf_content))
    return Response(content=pdf_content, media_type="application/pdf")
