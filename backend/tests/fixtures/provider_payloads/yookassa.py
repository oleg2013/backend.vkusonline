"""Sample YooKassa API payloads for contract tests."""

from __future__ import annotations

# Response from POST /v3/payments (payment creation)
PAYMENT_CREATED: dict = {
    "id": "2d7b5f6a-0001-4000-a000-1f0000000001",
    "status": "pending",
    "paid": False,
    "amount": {
        "value": "1500.00",
        "currency": "RUB",
    },
    "confirmation": {
        "type": "redirect",
        "confirmation_url": "https://yookassa.ru/checkout/payments/v2/contract?orderId=2d7b5f6a-0001",
    },
    "created_at": "2025-01-15T10:30:00.000+00:00",
    "description": "Order VK-250115-ABC123",
    "metadata": {
        "order_number": "VK-250115-ABC123",
    },
    "recipient": {
        "account_id": "100500",
        "gateway_id": "200600",
    },
    "refundable": False,
    "test": True,
}

# Webhook payload for payment.succeeded event
PAYMENT_SUCCEEDED: dict = {
    "type": "notification",
    "event": "payment.succeeded",
    "object": {
        "id": "2d7b5f6a-0001-4000-a000-1f0000000001",
        "status": "succeeded",
        "paid": True,
        "amount": {
            "value": "1500.00",
            "currency": "RUB",
        },
        "captured_at": "2025-01-15T10:32:00.000+00:00",
        "created_at": "2025-01-15T10:30:00.000+00:00",
        "description": "Order VK-250115-ABC123",
        "metadata": {
            "order_number": "VK-250115-ABC123",
        },
        "payment_method": {
            "type": "bank_card",
            "id": "2d7b5f6a-0001-4000-a000-1f0000000001",
            "saved": False,
            "card": {
                "first6": "411111",
                "last4": "1111",
                "expiry_month": "12",
                "expiry_year": "2025",
                "card_type": "Visa",
            },
            "title": "Bank card *1111",
        },
        "refundable": True,
        "test": True,
        "income_amount": {
            "value": "1455.00",
            "currency": "RUB",
        },
    },
}

# Webhook payload for payment.canceled event
PAYMENT_CANCELLED: dict = {
    "type": "notification",
    "event": "payment.canceled",
    "object": {
        "id": "2d7b5f6a-0002-4000-a000-1f0000000002",
        "status": "canceled",
        "paid": False,
        "amount": {
            "value": "750.00",
            "currency": "RUB",
        },
        "created_at": "2025-01-15T11:00:00.000+00:00",
        "description": "Order VK-250115-DEF456",
        "metadata": {
            "order_number": "VK-250115-DEF456",
        },
        "cancellation_details": {
            "party": "merchant",
            "reason": "canceled_by_merchant",
        },
        "refundable": False,
        "test": True,
    },
}
