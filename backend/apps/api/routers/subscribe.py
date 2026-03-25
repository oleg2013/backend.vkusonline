from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select

from apps.api.deps import DbSession
from packages.core.config import settings
from packages.models.subscriber import Subscriber

logger = structlog.get_logger("api.subscribe")

router = APIRouter(tags=["subscribe"])


class SubscribeRequest(BaseModel):
    email: EmailStr
    name: str | None = Field(default=None, max_length=255)
    source: str = Field(default="footer", max_length=50)


class SubscribeResponse(BaseModel):
    status: str  # "subscribed", "already_subscribed", "reactivated"
    message: str


@router.post("/subscribe")
async def subscribe(req: SubscribeRequest, db: DbSession) -> SubscribeResponse:
    """Subscribe to newsletter."""
    email_lower = req.email.lower().strip()

    # Check if already exists
    result = await db.execute(
        select(Subscriber).where(Subscriber.email == email_lower)
    )
    existing = result.scalar_one_or_none()

    if existing:
        if existing.is_active:
            # Re-send welcome email
            try:
                from packages.services.events import event_dispatcher
                await event_dispatcher.dispatch(
                    "client_event",
                    {
                        "event_name": "SUBSCRIBENEW",
                        "context": {
                            "EMAIL": email_lower,
                            "ORDER_USER": existing.name or email_lower,
                            "SUBSCRIBE_DATE": existing.created_at.strftime("%d.%m.%Y"),
                            "SERVER_NAME": settings.server_name,
                            "SHOP_NAME": settings.shop_name,
                            "SALE_EMAIL": settings.sale_email,
                            "SHOP_PHONE": settings.shop_phone,
                            "SYS_SHOP_EMAIL": settings.smtp_from_email,
                            "UNSUBSCRIBE_URL": f"https://{settings.server_name}/#/unsubscribe/{existing.unsubscribe_token}",
                        },
                    },
                )
            except Exception as exc:
                logger.warning("subscribe_resend_failed", error=str(exc))
            return SubscribeResponse(
                status="already_subscribed",
                message="Вы уже подписаны! Отправили приветственное письмо повторно.",
            )
        else:
            # Reactivate
            existing.is_active = True
            existing.unsubscribe_token = uuid.uuid4().hex
            await db.commit()
            logger.info("subscriber_reactivated", email=email_lower)
            # Send welcome email
            try:
                from packages.services.events import event_dispatcher
                await event_dispatcher.dispatch(
                    "client_event",
                    {
                        "event_name": "SUBSCRIBENEW",
                        "context": {
                            "EMAIL": email_lower,
                            "ORDER_USER": existing.name or email_lower,
                            "SUBSCRIBE_DATE": existing.created_at.strftime("%d.%m.%Y"),
                            "SERVER_NAME": settings.server_name,
                            "SHOP_NAME": settings.shop_name,
                            "SALE_EMAIL": settings.sale_email,
                            "SHOP_PHONE": settings.shop_phone,
                            "SYS_SHOP_EMAIL": settings.smtp_from_email,
                            "UNSUBSCRIBE_URL": f"https://{settings.server_name}/#/unsubscribe/{existing.unsubscribe_token}",
                        },
                    },
                )
            except Exception as exc:
                logger.warning("subscribe_reactivate_email_failed", error=str(exc))
            return SubscribeResponse(
                status="reactivated", message="Подписка восстановлена!"
            )

    # Create new subscriber
    subscriber = Subscriber(
        email=email_lower,
        name=req.name,
        source=req.source,
    )
    db.add(subscriber)
    await db.commit()

    logger.info("new_subscriber", email=email_lower, source=req.source)

    # Send welcome email + admin notification
    try:
        from packages.services.events import event_dispatcher

        await event_dispatcher.dispatch(
            "client_event",
            {
                "event_name": "SUBSCRIBENEW",
                "context": {
                    "EMAIL": email_lower,
                    "ORDER_USER": req.name or email_lower,
                    "SUBSCRIBE_DATE": subscriber.created_at.strftime("%d.%m.%Y"),
                    "SERVER_NAME": settings.server_name,
                    "SHOP_NAME": settings.shop_name,
                    "SALE_EMAIL": settings.sale_email,
                    "SHOP_PHONE": settings.shop_phone,
                    "SYS_SHOP_EMAIL": settings.smtp_from_email,
                    "UNSUBSCRIBE_URL": f"https://{settings.server_name}/#/unsubscribe/{subscriber.unsubscribe_token}",
                },
            },
        )
    except Exception as exc:
        logger.warning("subscribe_email_failed", error=str(exc))

    return SubscribeResponse(status="subscribed", message="Вы успешно подписались!")


def _unsubscribe_html(title: str, message: str) -> str:
    return f"""<!DOCTYPE html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title></head><body style="margin:0;padding:40px 16px;background:#FDF8F0;font-family:'Segoe UI',Roboto,sans-serif;text-align:center;">
<div style="max-width:480px;margin:0 auto;background:#fff;border-radius:16px;padding:40px;box-shadow:0 4px 24px rgba(0,0,0,0.06);">
<p style="font-size:40px;margin:0 0 16px;">&#9749;</p>
<h1 style="font-size:20px;color:#333;margin:0 0 12px;">{title}</h1>
<p style="font-size:15px;color:#666;margin:0 0 24px;">{message}</p>
<a href="https://{settings.server_name}/" style="display:inline-block;padding:12px 32px;background:#C8860A;color:#fff;text-decoration:none;border-radius:8px;font-size:14px;">Вернуться в магазин</a>
</div></body></html>"""


@router.get("/unsubscribe/{token}")
async def unsubscribe(token: str, db: DbSession):
    """Unsubscribe via token link — returns JSON for SPA frontend."""
    result = await db.execute(
        select(Subscriber).where(Subscriber.unsubscribe_token == token)
    )
    subscriber = result.scalar_one_or_none()

    if not subscriber:
        return {"status": "not_found", "message": "Ссылка недействительна"}

    if not subscriber.is_active:
        return {"status": "already_unsubscribed", "message": "Вы уже отписаны"}

    subscriber.is_active = False
    await db.commit()

    logger.info("subscriber_unsubscribed", email=subscriber.email)
    return {"status": "unsubscribed", "message": "Вы успешно отписались от рассылки"}
