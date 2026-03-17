"""Sample Magnit Post API payloads for contract tests."""

from __future__ import annotations

# OAuth2 token response
TOKEN_RESPONSE: dict = {
    "access_token": "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.test-magnit-token",
    "token_type": "bearer",
    "expires_in": 3600,
    "scope": "delivery",
}

# Response from GET /api/v2/pvz (pickup points list)
PICKUP_POINTS_RESPONSE: dict = {
    "data": [
        {
            "key": "MAG-PVZ-001",
            "name": "Magnit Express Moscow 1",
            "city": "Moscow",
            "address": "Moscow, Lenina 10",
            "lat": 55.7600,
            "lon": 37.6200,
            "region": "Moscow Oblast",
            "status": "ACTIVE",
            "work_schedule": [
                {"day": "MON", "opens_at": "08:00", "closes_at": "22:00"},
                {"day": "TUE", "opens_at": "08:00", "closes_at": "22:00"},
                {"day": "WED", "opens_at": "08:00", "closes_at": "22:00"},
                {"day": "THU", "opens_at": "08:00", "closes_at": "22:00"},
                {"day": "FRI", "opens_at": "08:00", "closes_at": "22:00"},
                {"day": "SAT", "opens_at": "09:00", "closes_at": "21:00"},
                {"day": "SUN", "opens_at": "09:00", "closes_at": "21:00"},
            ],
        },
        {
            "key": "MAG-PVZ-002",
            "name": "Magnit Express SPb 1",
            "city": "St Petersburg",
            "address": "St Petersburg, Nevsky 100",
            "lat": 59.9300,
            "lon": 30.3200,
            "region": "Leningrad Oblast",
            "status": "ACTIVE",
            "work_schedule": [
                {"day": "MON", "opens_at": "09:00", "closes_at": "21:00"},
                {"day": "TUE", "opens_at": "09:00", "closes_at": "21:00"},
                {"day": "WED", "opens_at": "09:00", "closes_at": "21:00"},
                {"day": "THU", "opens_at": "09:00", "closes_at": "21:00"},
                {"day": "FRI", "opens_at": "09:00", "closes_at": "21:00"},
                {"day": "SAT", "opens_at": "10:00", "closes_at": "20:00"},
                {"day": "SUN", "opens_at": "10:00", "closes_at": "20:00"},
            ],
        },
    ],
    "total": 2,
    "page": 1,
    "page_size": 100,
}

# Response from POST /api/v2/orders
ORDER_CREATED: dict = {
    "order_id": "magnit-order-uuid-001",
    "customer_order_id": "VK-250115-GHI789",
    "status": "CREATED",
    "pickup_point": {
        "key": "MAG-PVZ-001",
        "name": "Magnit Express Moscow 1",
    },
    "parcels": [
        {
            "parcel_id": "magnit-parcel-001",
            "tracking_number": "MGNT1234567890",
            "status": "CREATED",
        },
    ],
    "created_at": "2025-01-15T10:40:00.000+00:00",
    "estimated_delivery": {
        "min_days": 2,
        "max_days": 5,
    },
}
