from __future__ import annotations

import re

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.core.config import settings
from packages.core.utils import haversine_distance
from packages.integrations.fivepost.models import FivePostRate
from packages.integrations.fivepost.utils import calculate_delivery_cost
from packages.models.catalog import Product
from packages.models.pickup_point import PickupPointCache

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# City-name normalisation
# ---------------------------------------------------------------------------
# DaData returns cities as  "г Москва", "пгт Агинское", "с Абатское" …
# 5Post stores them as      "Москва г",  "Агинское пгт", "Абатское с" …
# Magnit stores them as     "Москва",    "Агрыз" …
#
# We strip the settlement-type token so that a plain ilike('%Москва%')
# matches all three formats.
# ---------------------------------------------------------------------------

_SETTLEMENT_TYPES = (
    # Sorted longest-first so "ст-ца" is tried before "ст", "п/ст" before "п"
    "ст-ца",
    "ж/д_ст",
    "п/ст",
    "пгт",
    "аул",
    "дп",
    "гп",
    "кп",
    "нп",
    "рп",
    "сл",
    "сп",
    "ст",
    "г",
    "д",
    "м",
    "п",
    "с",
    "х",
)

# Regex: match any settlement type at the START, followed by a space
_PREFIX_RE = re.compile(
    r"^(?:" + "|".join(re.escape(t) for t in _SETTLEMENT_TYPES) + r")\s+",
    re.IGNORECASE,
)


def _normalize_city_name(city: str) -> str:
    """Strip the DaData-style settlement-type prefix from a city name.

    "г Москва"     → "Москва"
    "пгт Агинское" → "Агинское"
    "Москва"       → "Москва"  (no change)
    """
    stripped = _PREFIX_RE.sub("", city.strip())
    return stripped or city.strip()


async def search_pickup_points(
    db: AsyncSession,
    provider: str,
    city: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
    limit: int = 50,
) -> list[dict]:
    stmt = select(PickupPointCache).where(PickupPointCache.provider == provider)

    if city:
        clean_city = _normalize_city_name(city)
        stmt = stmt.where(PickupPointCache.city.ilike(f"%{clean_city}%"))

    # When no distance sorting needed, apply LIMIT at SQL level for efficiency
    need_distance_sort = lat is not None and lon is not None
    if not need_distance_sort:
        stmt = stmt.limit(limit)

    result = await db.execute(stmt)
    points = list(result.scalars().all())

    point_dicts = []
    for p in points:
        # Extract work schedule from raw_data (both Magnit and 5Post)
        schedule: list[dict] = []
        if p.raw_data:
            raw_schedule = p.raw_data.get("work_schedule") or p.raw_data.get("work_hours") or []
            for entry in raw_schedule:
                if isinstance(entry, dict) and entry.get("day"):
                    schedule.append({
                        "day": entry.get("day", ""),
                        "opens_at": entry.get("opens_at", ""),
                        "closes_at": entry.get("closes_at", ""),
                    })

        d = {
            "id": p.external_id,
            "name": p.name,
            "type": p.point_type,
            "city": p.city,
            "full_address": p.full_address,
            "lat": p.lat,
            "lon": p.lon,
            "cash_allowed": p.cash_allowed,
            "card_allowed": p.card_allowed,
            "distance_km": 0.0,
            "work_schedule": schedule,
            "additional": p.raw_data.get("additional", "") if p.raw_data else "",
        }
        if need_distance_sort:
            d["distance_km"] = round(haversine_distance(lat, lon, p.lat, p.lon), 2)
        point_dicts.append(d)

    if need_distance_sort:
        point_dicts.sort(key=lambda x: x["distance_km"])
        return point_dicts[:limit]

    return point_dicts


async def get_magnit_cities(db: AsyncSession) -> list[dict]:
    stmt = (
        select(
            PickupPointCache.city,
            func.count(PickupPointCache.id).label("count"),
        )
        .where(PickupPointCache.provider == "magnit")
        .group_by(PickupPointCache.city)
        .order_by(PickupPointCache.city)
    )
    result = await db.execute(stmt)
    return [{"city": row.city, "pickup_points_count": row.count} for row in result.all()]


async def find_nearest_magnit_cities(
    db: AsyncSession,
    lat: float,
    lon: float,
    limit: int = 5,
) -> list[dict]:
    cities = await get_magnit_cities(db)

    # Get one point per city to calculate distance
    city_distances = []
    for city_info in cities:
        stmt = (
            select(PickupPointCache)
            .where(
                PickupPointCache.provider == "magnit",
                func.lower(PickupPointCache.city) == city_info["city"].lower(),
            )
            .limit(1)
        )
        result = await db.execute(stmt)
        point = result.scalar_one_or_none()
        if point:
            dist = haversine_distance(lat, lon, point.lat, point.lon)
            city_distances.append({
                "city": city_info["city"],
                "distance_km": round(dist, 1),
                "pickup_points_count": city_info["pickup_points_count"],
            })

    city_distances.sort(key=lambda x: x["distance_km"])
    return city_distances[:limit]


async def _calc_total_weight_grams(
    db: AsyncSession,
    cart_items: list[dict],
) -> int:
    """Calculate total weight in grams from cart items [{sku, quantity}]."""
    skus = [item["sku"] for item in cart_items]
    stmt = select(Product).where(Product.sku.in_(skus))
    result = await db.execute(stmt)
    products = {p.sku: p for p in result.scalars().all()}

    total = 0
    for item in cart_items:
        product = products.get(item["sku"])
        if product:
            total += product.weight_grams * item["quantity"]
    return total


def _extract_rates_list(raw_rates: dict | list | None) -> list[dict]:
    """Extract rates list from JSONB. Handles both {rates: [...]} and [...] formats."""
    if not raw_rates:
        return []
    if isinstance(raw_rates, dict):
        return raw_rates.get("rates", [])
    if isinstance(raw_rates, list):
        return raw_rates
    return []


def _parse_fivepost_min_cost(point: PickupPointCache, weight_mg: int) -> float | None:
    """Get minimum delivery cost for a 5Post PVZ from its cached rates."""
    rates_list = _extract_rates_list(point.rates)
    if not rates_list:
        return None

    valid_costs = []
    for r in rates_list:
        try:
            rate = FivePostRate(**r)
            if rate.rate_value_with_vat > 0:
                cost = calculate_delivery_cost(rate, weight_mg)
                valid_costs.append(cost)
        except Exception:
            continue

    return min(valid_costs) if valid_costs else None


async def get_delivery_options(
    db: AsyncSession,
    city: str,
    cart_items: list[dict],
) -> dict:
    """Get available delivery providers for a city with min costs.

    Args:
        db: Database session.
        city: City name for filtering PVZ.
        cart_items: List of {sku, quantity} dicts.

    Returns:
        Dict with providers list and card_payment_discount_percent.
    """
    total_weight_grams = await _calc_total_weight_grams(db, cart_items)
    weight_mg = total_weight_grams * 1000

    clean_city = _normalize_city_name(city)
    logger.info(
        "delivery.get_options",
        raw_city=city,
        clean_city=clean_city,
    )

    providers = []

    for provider_code, provider_name in [("5post", "5Post"), ("magnit", "Магнит")]:
        # Count PVZ in city
        count_stmt = (
            select(func.count(PickupPointCache.id))
            .where(
                PickupPointCache.provider == provider_code,
                PickupPointCache.city.ilike(f"%{clean_city}%"),
            )
        )
        count_result = await db.execute(count_stmt)
        count = count_result.scalar() or 0

        available = count > 0
        min_cost: float | None = None

        if available and provider_code == "5post":
            # Load a sample of PVZ with rates to find min cost
            pvz_stmt = (
                select(PickupPointCache)
                .where(
                    PickupPointCache.provider == "5post",
                    PickupPointCache.city.ilike(f"%{clean_city}%"),
                    PickupPointCache.rates.isnot(None),
                )
                .limit(100)
            )
            pvz_result = await db.execute(pvz_stmt)
            points = pvz_result.scalars().all()

            costs = []
            for p in points:
                c = _parse_fivepost_min_cost(p, weight_mg)
                if c is not None:
                    costs.append(c)
            if costs:
                min_cost = min(costs)

        elif available and provider_code == "magnit":
            min_cost = settings.magnit_flat_delivery_cost_rub

        providers.append({
            "provider": provider_code,
            "name": provider_name,
            "available": available,
            "pickup_points_count": count,
            "min_delivery_cost": min_cost,
            "estimated_days_min": 3 if provider_code == "5post" else 5,
            "estimated_days_max": 7 if provider_code == "5post" else 10,
        })

    return {
        "providers": providers,
        "card_payment_discount_percent": settings.card_payment_discount_percent,
        "free_delivery_threshold_rub": settings.free_delivery_threshold_rub,
        "fivepost_map_version": settings.fivepost_map_version,
    }


async def estimate_delivery_for_pvz(
    db: AsyncSession,
    provider: str,
    pickup_point_id: str,
    cart_items: list[dict],
) -> dict:
    """Calculate exact delivery cost for a specific PVZ.

    Args:
        db: Database session.
        provider: '5post' or 'magnit'.
        pickup_point_id: External ID of the pickup point.
        cart_items: List of {sku, quantity} dicts.

    Returns:
        Dict with delivery cost, point info, and payment flags.
    """
    total_weight_grams = await _calc_total_weight_grams(db, cart_items)
    weight_mg = total_weight_grams * 1000

    stmt = select(PickupPointCache).where(
        PickupPointCache.provider == provider,
        PickupPointCache.external_id == pickup_point_id,
    )
    result = await db.execute(stmt)
    point = result.scalar_one_or_none()

    if not point:
        raise ValueError(f"Pickup point {pickup_point_id} not found for provider {provider}")

    delivery_cost: float
    if provider == "5post":
        rates_list = _extract_rates_list(point.rates)
        best_cost: float | None = None
        for r in rates_list:
            try:
                rate = FivePostRate(**r)
                if rate.rate_value_with_vat > 0:
                    c = calculate_delivery_cost(rate, weight_mg)
                    if best_cost is None or c < best_cost:
                        best_cost = c
            except Exception:
                continue
        delivery_cost = best_cost if best_cost is not None else 0.0
    else:
        # magnit — flat rate
        delivery_cost = settings.magnit_flat_delivery_cost_rub

    return {
        "provider": provider,
        "pickup_point_id": point.external_id,
        "pickup_point_name": point.name,
        "delivery_cost": delivery_cost,
        "estimated_days_min": 3 if provider == "5post" else 5,
        "estimated_days_max": 7 if provider == "5post" else 10,
        "cash_allowed": point.cash_allowed or False,
        "card_allowed": point.card_allowed or False,
    }


async def get_cache_status(db: AsyncSession, provider: str) -> dict:
    count_stmt = (
        select(func.count(PickupPointCache.id))
        .where(PickupPointCache.provider == provider)
    )
    count_result = await db.execute(count_stmt)
    count = count_result.scalar() or 0

    last_sync_stmt = (
        select(func.max(PickupPointCache.synced_at))
        .where(PickupPointCache.provider == provider)
    )
    last_result = await db.execute(last_sync_stmt)
    last_synced = last_result.scalar()

    return {
        "provider": provider,
        "points_count": count,
        "last_synced_at": last_synced.isoformat() if last_synced else None,
    }
