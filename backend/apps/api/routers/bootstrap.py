from __future__ import annotations

from fastapi import APIRouter

from apps.api.deps import RequestId
from packages.core.config import settings

router = APIRouter(tags=["bootstrap"])


@router.get("/bootstrap")
async def bootstrap(request_id: RequestId):
    return {
        "ok": True,
        "data": {
            "delivery_providers": [
                {"id": "5post", "name": "5Post", "description": "Доставка в постаматы и ПВЗ"},
                {"id": "magnit", "name": "Магнит", "description": "Доставка в магазины Магнит"},
            ],
            "payment_providers": [
                {"id": "yookassa", "name": "ЮKassa", "confirmation_types": ["redirect"]},
            ],
            "payment_methods": [
                {"id": "card", "name": "Банковская карта", "description": f"Скидка {settings.card_payment_discount_percent}%"},
                {"id": "cod", "name": "Наложенный платёж", "description": "Оплата при получении"},
            ],
            "card_payment_discount_percent": settings.card_payment_discount_percent,
            "currency": "RUB",
            "min_order_amount": 500,
            "guest_session_required": True,
        },
        "request_id": request_id,
    }
