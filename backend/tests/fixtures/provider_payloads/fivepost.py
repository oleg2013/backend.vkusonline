"""Sample 5Post API payloads for contract tests."""

from __future__ import annotations

# Response from POST /api/v1/pickuppoints/query (single page)
PICKUP_POINTS_RESPONSE: dict = {
    "totalPages": 1,
    "totalElements": 2,
    "content": [
        {
            "id": "PP-001",
            "name": "Postamt Moscow Center",
            "type": "POSTAMAT",
            "fullAddress": "Moscow, Tverskaya 1",
            "shortAddress": "Tverskaya 1",
            "address": {
                "city": "Moscow",
                "street": "Tverskaya",
                "house": "1",
                "lat": 55.7558,
                "lng": 37.6173,
            },
            "cashAllowed": False,
            "cardAllowed": True,
            "rate": [
                {
                    "rateType": "STANDARD",
                    "rateValue": 170.0,
                    "rateValueWithVat": 200.0,
                    "rateExtraValue": 40.0,
                    "rateExtraValueWithVat": 50.0,
                    "zone": "MSK",
                    "rateCurrency": "RUB",
                    "vat": 20,
                },
            ],
            "cellLimits": {
                "maxCellWidth": 400,
                "maxCellHeight": 300,
                "maxCellLength": 600,
                "maxWeight": 5000000,
            },
            "workHours": [
                {"day": "MON", "opensAt": "08:00", "closesAt": "22:00"},
                {"day": "TUE", "opensAt": "08:00", "closesAt": "22:00"},
                {"day": "WED", "opensAt": "08:00", "closesAt": "22:00"},
                {"day": "THU", "opensAt": "08:00", "closesAt": "22:00"},
                {"day": "FRI", "opensAt": "08:00", "closesAt": "22:00"},
                {"day": "SAT", "opensAt": "10:00", "closesAt": "20:00"},
                {"day": "SUN", "opensAt": "10:00", "closesAt": "20:00"},
            ],
            "phone": "+74951234567",
            "partnerName": "5Post",
            "mdmCode": "MDM-001",
            "additional": "Near metro Tverskaya",
        },
        {
            "id": "PP-002",
            "name": "PVZ SPb Nevsky",
            "type": "PVZ",
            "fullAddress": "St Petersburg, Nevsky Prospekt 50",
            "shortAddress": "Nevsky 50",
            "address": {
                "city": "St Petersburg",
                "street": "Nevsky Prospekt",
                "house": "50",
                "lat": 59.9343,
                "lng": 30.3351,
            },
            "cashAllowed": True,
            "cardAllowed": True,
            "rate": [
                {
                    "rateType": "STANDARD",
                    "rateValue": 150.0,
                    "rateValueWithVat": 180.0,
                    "rateExtraValue": 35.0,
                    "rateExtraValueWithVat": 42.0,
                    "zone": "SPB",
                    "rateCurrency": "RUB",
                    "vat": 20,
                },
            ],
            "cellLimits": {
                "maxCellWidth": 500,
                "maxCellHeight": 400,
                "maxCellLength": 700,
                "maxWeight": 10000000,
            },
            "workHours": [
                {"day": "MON", "opensAt": "09:00", "closesAt": "21:00"},
                {"day": "TUE", "opensAt": "09:00", "closesAt": "21:00"},
                {"day": "WED", "opensAt": "09:00", "closesAt": "21:00"},
                {"day": "THU", "opensAt": "09:00", "closesAt": "21:00"},
                {"day": "FRI", "opensAt": "09:00", "closesAt": "21:00"},
                {"day": "SAT", "opensAt": "10:00", "closesAt": "18:00"},
                {"day": "SUN", "opensAt": "10:00", "closesAt": "18:00"},
            ],
            "phone": "+78121234567",
            "partnerName": "5Post",
            "mdmCode": "MDM-002",
            "additional": "Near metro Nevsky Prospekt",
        },
    ],
}

# Response from POST /api/v3/orders
ORDER_CREATED: dict = {
    "created": True,
    "orderId": "5post-order-uuid-001",
    "senderOrderId": "VK-250115-ABC123",
    "clientOrderId": "VK-250115-ABC123",
    "status": "CREATED",
    "errors": [],
}

# Webhook / callback payload for status update
WEBHOOK_STATUS_UPDATE: dict = {
    "orderId": "5post-order-uuid-001",
    "senderOrderId": "VK-250115-ABC123",
    "statusCode": "READY_FOR_PICKUP",
    "statusName": "Ready for pickup",
    "timestamp": "2025-01-17T14:30:00.000+00:00",
    "description": "The order is ready for pickup at the point.",
    "trackingEvents": [
        {
            "statusCode": "CREATED",
            "statusName": "Created",
            "timestamp": "2025-01-15T10:35:00.000+00:00",
            "description": "Order created",
        },
        {
            "statusCode": "ACCEPTED",
            "statusName": "Accepted",
            "timestamp": "2025-01-15T12:00:00.000+00:00",
            "description": "Order accepted by warehouse",
        },
        {
            "statusCode": "IN_TRANSIT",
            "statusName": "In transit",
            "timestamp": "2025-01-16T08:00:00.000+00:00",
            "description": "Order in transit",
        },
        {
            "statusCode": "READY_FOR_PICKUP",
            "statusName": "Ready for pickup",
            "timestamp": "2025-01-17T14:30:00.000+00:00",
            "description": "The order is ready for pickup at the point.",
        },
    ],
}
