from __future__ import annotations

from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, Request

from apps.api.deps import DbSession, RequestId
from packages.enums import PaymentStatus
from packages.models.provider import ProviderWebhookEvent
from packages.services import payments as payment_service

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/yookassa")
async def yookassa_webhook(
    request: Request,
    db: DbSession,
    request_id: RequestId,
):
    body = await request.json()

    # Store raw event
    event = ProviderWebhookEvent(
        provider="yookassa",
        event_type=body.get("event", "unknown"),
        external_id=body.get("object", {}).get("id"),
        payload=body,
        received_at=datetime.now(UTC),
    )
    db.add(event)
    await db.flush()

    # Process payment update
    obj = body.get("object", {})
    provider_payment_id = obj.get("id")
    if not provider_payment_id:
        logger.warning("yookassa_webhook_no_id", body=body)
        return {"ok": True, "data": {"status": "ignored"}, "request_id": request_id}

    payment = await payment_service.get_payment_by_provider_id(db, provider_payment_id)
    if not payment:
        logger.warning("yookassa_webhook_payment_not_found", provider_id=provider_payment_id)
        event.error_message = "Payment not found"
        return {"ok": True, "data": {"status": "not_found"}, "request_id": request_id}

    status_map = {
        "payment.succeeded": PaymentStatus.SUCCEEDED,
        "payment.canceled": PaymentStatus.CANCELLED,
        "payment.waiting_for_capture": PaymentStatus.WAITING_CAPTURE,
    }

    event_type = body.get("event")
    new_status = status_map.get(event_type)

    if new_status:
        await payment_service.update_payment_from_provider(
            db, payment, provider_payment_id, new_status, provider_payload=obj
        )

        if new_status == PaymentStatus.SUCCEEDED:
            await payment_service.process_payment_success(db, payment)
        elif new_status == PaymentStatus.CANCELLED:
            await payment_service.process_payment_cancelled(db, payment)

        event.processed = True

    logger.info(
        "yookassa_webhook_processed",
        event_type=event_type,
        payment_id=provider_payment_id,
        new_status=new_status,
    )

    return {"ok": True, "data": {"status": "processed"}, "request_id": request_id}


@router.post("/5post")
async def fivepost_webhook(
    request: Request,
    db: DbSession,
    request_id: RequestId,
):
    body = await request.json()

    event = ProviderWebhookEvent(
        provider="5post",
        event_type=body.get("status", "unknown"),
        external_id=body.get("senderOrderId"),
        payload=body,
        received_at=datetime.now(UTC),
    )
    db.add(event)
    await db.flush()

    # TODO: process 5Post status update -> update shipment
    logger.info("fivepost_webhook_received", body=body)

    return {"ok": True, "data": {"status": "received"}, "request_id": request_id}
