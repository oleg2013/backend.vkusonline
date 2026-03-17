"""Event handlers that queue emails when order status changes."""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

import structlog

from packages.core.config import settings
from packages.core.redis import get_redis
from packages.services.email.templates import (
    build_order_context,
    fetch_pvz_details,
    find_templates,
    render_template,
)

logger = structlog.get_logger(__name__)

# Path to email templates root directory
TEMPLATES_ROOT = "templates/email"


async def _queue_email(to: str, subject: str, body: str, from_addr: str | None = None) -> None:
    """Push email to Redis reliable queue (Hash + Sorted Set) for Worker to send."""
    redis = await get_redis()
    msg_id = str(uuid.uuid4())
    payload = json.dumps({
        "msg_id": msg_id,
        "to": to,
        "subject": subject,
        "body": body,
        "from_addr": from_addr,
        "_retries": 0,
        "_created_at": time.time(),
    })
    await redis.hset("email:msgs", msg_id, payload)
    await redis.zadd("email:pending", {msg_id: time.time()})
    logger.info("email_queued", to=to, subject=subject, msg_id=msg_id)


async def _get_pvz_data(order) -> dict[str, Any] | None:
    """Fetch PVZ details from cache if the order has a pickup point."""
    provider = getattr(order, "delivery_provider", "") or ""
    pvz_id = getattr(order, "pickup_point_id", "") or ""
    if provider and pvz_id:
        try:
            return await fetch_pvz_details(provider, pvz_id)
        except Exception as exc:
            logger.warning("pvz_details_fetch_failed", provider=provider, pvz_id=pvz_id, error=str(exc))
    return None


async def on_order_status_changed(data: dict[str, Any]) -> None:
    """Handle order_status_changed event — find templates, queue emails, auto-create shipment."""
    order = data["order"]
    new_status = data["new_status"]
    extra_context = data.get("extra_context", {})

    # Enqueue shipment creation when order moves to SHIPPED
    if new_status == "shipped":
        try:
            from apps.worker.jobs.process_shipments import enqueue_shipment
            await enqueue_shipment(order.id, order.order_number)
        except Exception as exc:
            logger.error("shipment_enqueue_failed", order_number=order.order_number, error=str(exc))

    templates = find_templates(TEMPLATES_ROOT, order.order_type, new_status)
    if not templates:
        logger.debug("no_email_templates", order_type=order.order_type, status=new_status)
        return

    pvz_data = await _get_pvz_data(order)
    context = build_order_context(order, extra_context, pvz_data=pvz_data)

    for tmpl in templates:
        rendered = render_template(tmpl, context, templates_root=TEMPLATES_ROOT)
        if rendered.to:
            await _queue_email(rendered.to, rendered.subject, rendered.body, rendered.from_addr)


async def on_order_created(data: dict[str, Any]) -> None:
    """Handle order_created event — send initial notification."""
    order = data["order"]
    extra_context = data.get("extra_context", {})

    # For order creation, the status IS the event name
    # e.g., CODFLOW + PENDING_CONFIRMATION, PREPAID + PENDING_PAYMENT
    templates = find_templates(TEMPLATES_ROOT, order.order_type, order.status)
    if not templates:
        logger.debug("no_email_templates_for_creation", order_type=order.order_type, status=order.status)
        return

    pvz_data = await _get_pvz_data(order)
    context = build_order_context(order, extra_context, pvz_data=pvz_data)

    for tmpl in templates:
        rendered = render_template(tmpl, context, templates_root=TEMPLATES_ROOT)
        if rendered.to:
            await _queue_email(rendered.to, rendered.subject, rendered.body, rendered.from_addr)


async def on_client_event(data: dict[str, Any]) -> None:
    """Handle client events (CLIENTNEW, CLIENTRESETPASS, CLIENTREMINDPASS)."""
    event_name = data["event_name"]  # e.g., "CLIENTNEW"
    extra_context = data.get("context", {})

    templates = find_templates(TEMPLATES_ROOT, "OTHERS", event_name)
    if not templates:
        logger.debug("no_email_templates_for_client_event", event_name=event_name)
        return

    for tmpl in templates:
        rendered = render_template(tmpl, extra_context, templates_root=TEMPLATES_ROOT)
        if rendered.to:
            await _queue_email(rendered.to, rendered.subject, rendered.body, rendered.from_addr)
