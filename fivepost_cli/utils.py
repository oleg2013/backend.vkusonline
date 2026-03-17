"""
Утилиты для расчётов: расстояние, вес, стоимость доставки, генерация ID.
"""

import math
import random
import string
from typing import Optional

from models import Product, PickupPoint, Rate
import config


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Расчёт расстояния между двумя точками по формуле гаверсинуса.
    Возвращает расстояние в километрах.
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


def calculate_cargo_weight_mg(products: list[Product]) -> int:
    """
    Расчёт веса грузоместа в миллиграммах.
    Формула: вес_товаров + max(вес_товаров * 20%, 300г)
    """
    total_product_weight_g = sum(p.weight_grams * p.quantity for p in products)
    packaging_weight_g = max(
        total_product_weight_g * config.PACKAGING_WEIGHT_PERCENT,
        config.MIN_PACKAGING_WEIGHT_G
    )
    total_weight_g = total_product_weight_g + packaging_weight_g
    # Конвертация граммы -> миллиграммы для API 5Post
    return int(total_weight_g * 1000)


def calculate_cargo_weight_display(products: list[Product]) -> tuple[float, float]:
    """
    Расчёт веса для отображения пользователю.
    Возвращает: (вес_товаров_г, вес_упаковки_г)
    """
    total_product_weight_g = sum(p.weight_grams * p.quantity for p in products)
    packaging_weight_g = max(
        total_product_weight_g * config.PACKAGING_WEIGHT_PERCENT,
        config.MIN_PACKAGING_WEIGHT_G
    )
    return total_product_weight_g, packaging_weight_g


def get_best_rate(point: PickupPoint) -> Optional[Rate]:
    """
    Получить лучший (минимальный) тариф для точки выдачи.
    Пропускает тарифы с нулевой стоимостью (ещё не прогружены).
    """
    valid_rates = [r for r in point.rates if r.rate_value_with_vat > 0]
    if not valid_rates:
        return None
    return min(valid_rates, key=lambda r: r.rate_value_with_vat)


def calculate_delivery_cost(point: PickupPoint, weight_mg: int) -> float:
    """
    Расчёт стоимости доставки до точки выдачи.
    Формула: rateValueWithVat + rateExtraValueWithVat * ceil(перевес_кг)
    Перевес считается свыше 3 кг.
    Возвращает стоимость в рублях.
    """
    rate = get_best_rate(point)
    if rate is None:
        return 0.0

    weight_kg = weight_mg / 1_000_000
    cost = rate.rate_value_with_vat

    if weight_kg > config.OVERWEIGHT_THRESHOLD_KG:
        overweight_kg = math.ceil(weight_kg - config.OVERWEIGHT_THRESHOLD_KG)
        cost += rate.rate_extra_value_with_vat * overweight_kg

    return round(cost, 2)


def calculate_total_products_price(products: list[Product]) -> float:
    """Суммарная стоимость всех товаров."""
    return round(sum(p.total_price for p in products), 2)


def calculate_insurance_fee(products_sum: float) -> float:
    """
    Расчёт страховки (приём с объявленной ценности).
    Формула: стоимость_товаров / 100 * 0.5
    """
    return round(products_sum / 100 * config.INSURANCE_PERCENT, 2)


def calculate_cod_commission(products_sum: float, commission_percent: float) -> float:
    """
    Расчёт комиссии за перевод наложенного платежа.
    Формула: стоимость_товаров / (100 - процент) * 100 - стоимость_товаров
    Например при 2.5%: 5500 / 97.5 * 100 - 5500 = 141.03
    """
    return round(products_sum / (100 - commission_percent) * 100 - products_sum, 2)


def calculate_total_order_cost(
    products_sum: float,
    delivery_cost: float,
    payment_type: str,
    payment_method: Optional[str] = None,
) -> tuple[float, float, float]:
    """
    Полный расчёт стоимости заказа для клиента.
    Возвращает: (страховка, комиссия_НП, итого)

    Предоплата:    товары + доставка + страховка
    НП наличными:  товары + доставка + комиссия_1.5% + страховка
    НП картой:     товары + доставка + комиссия_2.5% + страховка
    """
    insurance_fee = calculate_insurance_fee(products_sum)

    if payment_type == "prepaid":
        total = round(products_sum + delivery_cost + insurance_fee, 2)
        return insurance_fee, 0.0, total

    # Наложенный платёж
    if payment_method == "card":
        commission = calculate_cod_commission(products_sum, config.COD_CARD_COMMISSION_PERCENT)
    else:  # cash
        commission = calculate_cod_commission(products_sum, config.COD_CASH_COMMISSION_PERCENT)

    total = round(products_sum + delivery_cost + commission + insurance_fee, 2)
    return insurance_fee, commission, total


def generate_order_id() -> str:
    """
    Генерация уникального номера заказа.
    Формат: ORD-XXXXXXXX (латиница + цифры + тире).
    """
    chars = string.ascii_uppercase + string.digits
    random_part = ''.join(random.choices(chars, k=8))
    return f"ORD-{random_part}"


def generate_cargo_id() -> str:
    """
    Генерация уникального ID грузоместа.
    Формат: CRG-XXXXXXXX (латиница + цифры).
    """
    chars = string.ascii_uppercase + string.digits
    random_part = ''.join(random.choices(chars, k=8))
    return f"CRG-{random_part}"


def format_weight(weight_mg: int) -> str:
    """Форматирование веса из миллиграммов в читаемый вид."""
    weight_g = weight_mg / 1000
    if weight_g >= 1000:
        return f"{weight_g / 1000:.2f} кг"
    return f"{weight_g:.0f} г"


def mask_token(token: str) -> str:
    """Маскирование JWT-токена для логов (первые 10 + ... + последние 10 символов)."""
    if len(token) <= 25:
        return "***"
    return f"{token[:10]}...{token[-10:]}"
