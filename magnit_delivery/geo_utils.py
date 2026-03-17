"""
Утилиты: расчёт расстояний, генерация ID, форматирование.
"""

import math
import random
import string
import re
from datetime import datetime


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Рассчитывает расстояние между двумя точками на Земле (в км)
    по формуле Haversine.
    """
    R = 6371.0  # Радиус Земли в км

    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)

    a = (math.sin(dlat / 2) ** 2 +
         math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return R * c


def generate_order_id() -> str:
    """
    Генерирует уникальный номер заказа.
    Формат: ORD-XXXX-YYYYMMDD-XXXX (латинские буквы, цифры, тире).
    Пример: ORD-A7K3-20260304-M9X2
    """
    def _random_block(length: int) -> str:
        chars = string.ascii_uppercase + string.digits
        return ''.join(random.choices(chars, k=length))

    date_part = datetime.now().strftime("%Y%m%d")
    return f"ORD-{_random_block(4)}-{date_part}-{_random_block(4)}"


def calculate_delivery_cost_kopecks(cost_without_vat_rub: float, vat_rate_percent: float) -> int:
    """
    Рассчитывает стоимость доставки с НДС в копейках.
    Пример: 150 руб без НДС, НДС 22% → 183 руб = 18300 коп.
    """
    total_rub = cost_without_vat_rub * (1 + vat_rate_percent / 100)
    return round(total_rub * 100)


def delivery_cost_rub(cost_without_vat_rub: float, vat_rate_percent: float) -> float:
    """
    Рассчитывает стоимость доставки с НДС в рублях.
    """
    return round(cost_without_vat_rub * (1 + vat_rate_percent / 100), 2)


def format_phone(raw: str) -> str:
    """
    Нормализует телефонный номер в формат +7XXXXXXXXXX.
    Принимает: 89991234567, +79991234567, 8(999)123-45-67, итд.
    """
    digits = re.sub(r'\D', '', raw)

    if len(digits) == 11:
        if digits.startswith('8') or digits.startswith('7'):
            digits = '7' + digits[1:]
    elif len(digits) == 10:
        digits = '7' + digits
    else:
        # Возвращаем как есть если не удалось нормализовать
        return '+' + digits

    return '+' + digits


def mask_secret(value: str, visible_chars: int = 6) -> str:
    """
    Маскирует секретное значение для логов.
    Пример: "f4e2b7fi23ULPAPeTZdy" → "f4e2b7***"
    """
    if not value or len(value) <= visible_chars:
        return "***"
    return value[:visible_chars] + "***"


def mask_bearer_token(token: str) -> str:
    """
    Маскирует Bearer-токен для логов.
    Пример: "eyJhbGciOi..." → "eyJhbG***"
    """
    if not token:
        return "***"
    return token[:7] + "***" if len(token) > 7 else "***"


def safe_headers_for_log(headers: dict) -> dict:
    """
    Возвращает копию заголовков с замаскированными секретами.
    """
    safe = {}
    for key, value in headers.items():
        lower_key = key.lower()
        if lower_key == 'authorization':
            if value.startswith('Bearer '):
                safe[key] = 'Bearer ' + mask_bearer_token(value[7:])
            else:
                safe[key] = mask_secret(value)
        elif 'secret' in lower_key or 'token' in lower_key or 'key' in lower_key:
            safe[key] = mask_secret(str(value))
        else:
            safe[key] = value
    return safe
