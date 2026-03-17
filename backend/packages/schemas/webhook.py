from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# YooKassa webhook
# ---------------------------------------------------------------------------

class YooKassaWebhookPayload(BaseModel):
    """Incoming YooKassa webhook notification.

    Reference: https://yookassa.ru/developers/using-api/webhooks
    """

    type: str = Field(..., description="Notification type, e.g. 'notification'")
    event: str = Field(..., description="Event name, e.g. 'payment.succeeded'")
    object: dict[str, Any] = Field(..., description="Payment / refund object from YooKassa")


# ---------------------------------------------------------------------------
# 5Post webhook
# ---------------------------------------------------------------------------

class FivePostWebhookPayload(BaseModel):
    """Incoming 5Post status-change webhook.

    Fields depend on the actual 5Post / X5 API contract; we store the raw
    payload and parse it during processing.
    """

    senderOrderId: str | None = Field(default=None, description="Our order number sent to 5Post")
    orderNumber: str | None = Field(default=None, description="5Post internal order number")
    status: str | None = Field(default=None, description="New shipment status code")
    statusName: str | None = Field(default=None, description="Human-readable status name")
    statusDate: str | None = Field(default=None, description="ISO-8601 timestamp of the status change")
    trackNumber: str | None = Field(default=None, description="Tracking number if assigned")
    extra: dict[str, Any] | None = Field(default=None, description="Any additional provider-specific data")
