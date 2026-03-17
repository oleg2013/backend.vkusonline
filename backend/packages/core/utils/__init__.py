from __future__ import annotations

import math
import re
import secrets
import string
from datetime import UTC, datetime


def utcnow() -> datetime:
    return datetime.now(UTC)


def generate_order_number() -> str:
    ts = datetime.now(UTC).strftime("%y%m%d")
    rand = "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(6))
    return f"VK-{ts}-{rand}"


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    )
    return R * 2 * math.asin(math.sqrt(a))


def validate_phone(phone: str) -> str | None:
    cleaned = re.sub(r"[^\d+]", "", phone)
    if cleaned.startswith("8") and len(cleaned) == 11:
        cleaned = "+7" + cleaned[1:]
    elif cleaned.startswith("7") and len(cleaned) == 11:
        cleaned = "+" + cleaned
    elif cleaned.startswith("9") and len(cleaned) == 10:
        cleaned = "+7" + cleaned
    if re.match(r"^\+7\d{10}$", cleaned):
        return cleaned
    return None


def validate_email(email: str) -> bool:
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email))
