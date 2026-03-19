"""5Post API emulator endpoints.

Implements the subset of 5Post API that our backend client actually calls:
- POST /jwt-generate-claims/rs256/1  — JWT token
- POST /api/v3/orders                — create order
- GET  /api/v1/orders/{id}/status    — get order status
- DELETE /api/v1/orders/{id}         — cancel order
- GET  /api/v1/orders/{id}/label     — get label (stub PDF)
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import EmulFivePostOrder, EmulFivePostStatusHistory, get_db

router = APIRouter()
log = logging.getLogger("emulator.5post")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


# ── JWT token (stub) ────────────────────────────────────────────────

@router.post("/jwt-generate-claims/rs256/1")
async def jwt_generate(request: Request):
    """Return a dummy JWT token. Accepts any apikey."""
    import base64, json, time

    apikey = request.query_params.get("apikey", "unknown")
    log.info("[5POST] JWT requested  apikey=%s  ip=%s", apikey, request.client.host if request.client else "-")

    header = base64.urlsafe_b64encode(json.dumps({"alg": "RS256", "typ": "JWT"}).encode()).decode().rstrip("=")
    exp = int(time.time()) + 3600
    payload = base64.urlsafe_b64encode(json.dumps({
        "sub": "OpenAPI",
        "aud": "A122019!",
        "exp": exp,
        "iat": int(time.time()),
    }).encode()).decode().rstrip("=")
    signature = base64.urlsafe_b64encode(b"emulator-signature-stub").decode().rstrip("=")
    token = f"{header}.{payload}.{signature}"

    log.info("[5POST] JWT issued  exp=%s  token_len=%d", exp, len(token))
    return {"status": "ok", "jwt": token}


# ── Create order ────────────────────────────────────────────────────

@router.post("/api/v3/orders")
async def create_order(request: Request, db: AsyncSession = Depends(get_db)):
    """Create an order — emulates POST /api/v3/orders."""
    body = await request.json()
    partner_orders = body.get("partnerOrders", [])
    log.info("[5POST] Create order  count=%d  ip=%s", len(partner_orders), request.client.host if request.client else "-")

    results = []
    for po in partner_orders:
        sender_order_id = po.get("senderOrderId", "")
        client_name = po.get("clientName", "")
        receiver_location = po.get("receiverLocation", "")
        cost = po.get("cost", {})
        payment_value = cost.get("paymentValue", 0)
        payment_type = cost.get("paymentType", "")

        log.info("[5POST] Processing  sender_order_id=%s  client=%s  pvz=%s  payment=%.2f %s",
                 sender_order_id, client_name, receiver_location[:8] if receiver_location else "-",
                 payment_value, payment_type)

        # Check duplicate
        existing = await db.execute(
            select(EmulFivePostOrder).where(EmulFivePostOrder.sender_order_id == sender_order_id)
        )
        if existing.scalar_one_or_none():
            log.warning("[5POST] Duplicate rejected  sender_order_id=%s", sender_order_id)
            results.append({
                "created": False,
                "senderOrderId": sender_order_id,
                "errors": [{"code": 20, "message": f"Duplicate senderOrderId: {sender_order_id}"}],
            })
            continue

        order_id = uuid.uuid4()
        cargo_id = uuid.uuid4()
        cargoes = po.get("cargoes", [{}])
        first_cargo = cargoes[0] if cargoes else {}
        sender_cargo_id = first_cargo.get("senderCargoId", "")
        barcode = ""
        barcodes = first_cargo.get("barcodes", [])
        if barcodes:
            barcode = barcodes[0].get("value", "")
        if not barcode:
            barcode = f"FP{uuid.uuid4().hex[:12].upper()}"

        order = EmulFivePostOrder(
            order_id=order_id,
            sender_order_id=sender_order_id,
            client_order_id=po.get("clientOrderId", ""),
            client_name=client_name,
            client_phone=po.get("clientPhone", ""),
            client_email=po.get("clientEmail", ""),
            receiver_location=receiver_location,
            sender_location=po.get("senderLocation", ""),
            status="NEW",
            execution_status="CREATED",
            mile_type=None,
            payment_value=payment_value,
            payment_type=payment_type,
            order_data=po,
            cargo_id=cargo_id,
            sender_cargo_id=sender_cargo_id,
            barcode=barcode,
        )
        db.add(order)

        history = EmulFivePostStatusHistory(
            order_id=order_id,
            status="NEW",
            execution_status="CREATED",
            mile_type=None,
            change_date=_utcnow(),
        )
        db.add(history)

        log.info("[5POST] Order created  order_id=%s  sender_order_id=%s  barcode=%s  status=NEW/CREATED",
                 order_id, sender_order_id, barcode)

        results.append({
            "created": True,
            "orderId": str(order_id),
            "senderOrderId": sender_order_id,
            "cargoes": [{
                "cargoId": str(cargo_id),
                "senderCargoId": sender_cargo_id,
                "barcode": barcode,
            }],
        })

    await db.flush()
    return results


# ── Get order status ────────────────────────────────────────────────

@router.get("/api/v1/orders/{order_id}/status")
async def get_order_status(order_id: str, db: AsyncSession = Depends(get_db)):
    """Return current status and tracking history for an order."""
    log.info("[5POST] Get status  order_id=%s", order_id)

    try:
        uid = uuid.UUID(order_id)
    except ValueError:
        log.warning("[5POST] Invalid UUID  order_id=%s", order_id)
        return Response(
            content='{"error": true, "errorMessage": "Invalid UUID"}',
            status_code=400,
            media_type="application/json",
        )

    result = await db.execute(
        select(EmulFivePostOrder).where(EmulFivePostOrder.order_id == uid)
    )
    order = result.scalar_one_or_none()
    if not order:
        log.warning("[5POST] Order not found  order_id=%s", order_id)
        return Response(
            content='{"error": true, "errorMessage": "Order not found"}',
            status_code=404,
            media_type="application/json",
        )

    hist_result = await db.execute(
        select(EmulFivePostStatusHistory)
        .where(EmulFivePostStatusHistory.order_id == uid)
        .order_by(EmulFivePostStatusHistory.change_date)
    )
    history_rows = hist_result.scalars().all()

    tracking_events = []
    for h in history_rows:
        tracking_events.append({
            "statusCode": h.execution_status,
            "statusName": h.execution_status.replace("_", " ").title(),
            "timestamp": _iso(h.change_date),
            "description": h.error_desc or "",
        })

    log.info("[5POST] Status response  order_id=%s  sender=%s  status=%s/%s  mile=%s  history_count=%d",
             order_id, order.sender_order_id, order.status, order.execution_status,
             order.mile_type or "-", len(tracking_events))

    return {
        "orderId": str(order.order_id),
        "senderOrderId": order.sender_order_id,
        "statusCode": order.execution_status,
        "statusName": order.execution_status.replace("_", " ").title(),
        "status": order.status,
        "mileType": order.mile_type,
        "trackingEvents": tracking_events,
    }


# ── Cancel order ────────────────────────────────────────────────────

@router.delete("/api/v1/orders/{order_id}")
async def cancel_order(order_id: str, db: AsyncSession = Depends(get_db)):
    """Cancel an order by its UUID."""
    log.info("[5POST] Cancel request  order_id=%s", order_id)

    try:
        uid = uuid.UUID(order_id)
    except ValueError:
        log.warning("[5POST] Cancel invalid UUID  order_id=%s", order_id)
        return Response(
            content='{"error": true, "errorMessage": "Invalid UUID"}',
            status_code=400,
            media_type="application/json",
        )

    result = await db.execute(
        select(EmulFivePostOrder).where(EmulFivePostOrder.order_id == uid)
    )
    order = result.scalar_one_or_none()
    if not order:
        log.warning("[5POST] Cancel: order not found  order_id=%s", order_id)
        return {"error": True, "errorMessage": "Order not found", "errorCode": 600}

    if order.status in ("DONE", "CANCELLED"):
        log.warning("[5POST] Cancel: terminal status  order_id=%s  status=%s", order_id, order.status)
        return {"error": True, "errorMessage": "Terminal status, cancel impossible", "errorCode": 620, "canBeRetriedLater": False}

    if order.status == "NEW":
        log.info("[5POST] Cancel: status NEW, retry later  order_id=%s", order_id)
        return {"error": True, "errorMessage": "Cannot cancel right now, retry later", "errorCode": 610, "canBeRetriedLater": True}

    now = _utcnow()
    old_status = f"{order.status}/{order.execution_status}"
    order.status = "CANCELLED"
    order.execution_status = "CANCELLED"
    order.updated_at = now

    db.add(EmulFivePostStatusHistory(
        order_id=uid,
        status="CANCELLED",
        execution_status="CANCELLED",
        mile_type=order.mile_type,
        change_date=now,
    ))

    await db.flush()
    log.info("[5POST] Order cancelled  order_id=%s  sender=%s  was=%s", order_id, order.sender_order_id, old_status)
    return {"error": False}


# ── Get label (stub) ────────────────────────────────────────────────

@router.get("/api/v1/orders/{order_id}/label")
async def get_label(order_id: str, db: AsyncSession = Depends(get_db)):
    """Return a stub PDF label."""
    log.info("[5POST] Label request  order_id=%s", order_id)

    try:
        uid = uuid.UUID(order_id)
    except ValueError:
        return Response(status_code=400, content=b"Invalid UUID")

    result = await db.execute(
        select(EmulFivePostOrder).where(EmulFivePostOrder.order_id == uid)
    )
    order = result.scalar_one_or_none()
    if not order:
        log.warning("[5POST] Label: order not found  order_id=%s", order_id)
        return Response(status_code=404, content=b"Order not found")

    pdf_content = (
        b"%PDF-1.0\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R/Resources<<>>>>endobj\n"
        b"xref\n0 4\n0000000000 65535 f \n0000000009 00000 n \n"
        b"0000000058 00000 n \n0000000115 00000 n \n"
        b"trailer<</Size 4/Root 1 0 R>>\nstartxref\n229\n%%EOF"
    )
    log.info("[5POST] Label served  order_id=%s  sender=%s  size=%d bytes", order_id, order.sender_order_id, len(pdf_content))
    return Response(content=pdf_content, media_type="application/pdf")
