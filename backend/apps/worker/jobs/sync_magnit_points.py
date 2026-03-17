from __future__ import annotations

import asyncio
import json
import re
from datetime import UTC, datetime
from pathlib import Path

import structlog
from sqlalchemy import delete, select

from packages.core.db import async_session_factory
from packages.integrations.geo.dadata_client import get_client as get_dadata_client
from packages.integrations.magnit.client import get_client
from packages.models.pickup_point import PickupPointCache

logger = structlog.get_logger(__name__)

# Directory for saving original API responses for debugging
_PVZ_CACHE_DIR = Path("data/pvz_cache")

# ---------------------------------------------------------------------------
#  Address cleaning
# ---------------------------------------------------------------------------

# Parenthetical notes at the end of Magnit addresses, e.g.
# "(магазин Магнит)", "(ПВЗ KazanExpress)", etc.
_PAREN_TAIL_RE = re.compile(r"\s*\([^)]*\)\s*$")


def _clean_address_for_geocoding(city: str, raw_address: str) -> str:
    """Prepare a Magnit address for DaData geocoding.

    1. Strip the trailing parenthetical note  ("(магазин Магнит)").
    2. Prepend the city if it's not already present.
    """
    addr = _PAREN_TAIL_RE.sub("", raw_address).strip().rstrip(",")
    if city and addr and city.lower() not in addr.lower():
        addr = f"{city}, {addr}"
    return addr


# ---------------------------------------------------------------------------
#  Geocoding helpers
# ---------------------------------------------------------------------------

_GEOCODE_BATCH_SIZE = 5  # concurrent requests per batch
_GEOCODE_BATCH_DELAY = 0.5  # seconds between batches (DaData rate-limit ~20 rps)


async def _geocode_one(
    dadata, address: str
) -> tuple[float, float] | None:
    """Geocode a single address; return (lat, lon) or None."""
    try:
        return await dadata.geocode_address(address)
    except Exception as exc:  # noqa: BLE001
        logger.warning("geocode_failed", address=address[:80], error=str(exc))
        return None


async def _geocode_batch(
    dadata,
    entries: list[tuple[int, str]],
) -> dict[int, tuple[float, float]]:
    """Geocode a list of (index, address) tuples in batches.

    Returns a mapping of index → (lat, lon) for successfully geocoded items.
    """
    results: dict[int, tuple[float, float]] = {}
    total = len(entries)

    for batch_start in range(0, total, _GEOCODE_BATCH_SIZE):
        batch = entries[batch_start : batch_start + _GEOCODE_BATCH_SIZE]
        coros = [_geocode_one(dadata, addr) for _, addr in batch]
        batch_results = await asyncio.gather(*coros)

        for (idx, _addr), coords in zip(batch, batch_results):
            if coords:
                results[idx] = coords

        done = min(batch_start + _GEOCODE_BATCH_SIZE, total)
        if done % 500 == 0 or done == total:
            logger.info(
                "sync_magnit_geocoding_progress",
                done=done,
                total=total,
                resolved=len(results),
            )

        if batch_start + _GEOCODE_BATCH_SIZE < total:
            await asyncio.sleep(_GEOCODE_BATCH_DELAY)

    return results


# ---------------------------------------------------------------------------
#  Main sync function
# ---------------------------------------------------------------------------


async def sync_magnit_points() -> None:
    logger.info("sync_magnit_points_started")
    try:
        client = get_client()
        points = await client.get_pickup_points()
        logger.info("sync_magnit_fetched", count=len(points))

        # --- Save original API response as JSON for debugging -----------
        try:
            _PVZ_CACHE_DIR.mkdir(parents=True, exist_ok=True)
            cache_file = _PVZ_CACHE_DIR / "magnit_pvz_all.json"
            raw_list = [p.model_dump(by_alias=False) for p in points]
            cache_file.write_text(
                json.dumps(raw_list, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            size_mb = cache_file.stat().st_size / (1024 * 1024)
            logger.info(
                "sync_magnit_json_saved",
                path=str(cache_file),
                size_mb=round(size_mb, 2),
                count=len(raw_list),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("sync_magnit_json_save_failed", error=str(exc))

        # --- Geocode points that lack coordinates -----------------------
        need_geocoding: list[tuple[int, str]] = []
        for idx, p in enumerate(points):
            if not p.lat or not p.lon:
                addr = _clean_address_for_geocoding(p.city or "", p.address or "")
                if addr:
                    need_geocoding.append((idx, addr))

        geocoded: dict[int, tuple[float, float]] = {}
        if need_geocoding:
            logger.info("sync_magnit_geocoding_start", count=len(need_geocoding))
            dadata = get_dadata_client()
            geocoded = await _geocode_batch(dadata, need_geocoding)
            logger.info(
                "sync_magnit_geocoding_done",
                requested=len(need_geocoding),
                resolved=len(geocoded),
            )

        # --- Persist to DB -----------------------------------------------
        async with async_session_factory() as db:
            # Preserve previously geocoded coordinates before deleting old data
            old_coords: dict[str, tuple[float, float]] = {}
            old_stmt = select(PickupPointCache).where(
                PickupPointCache.provider == "magnit"
            )
            old_result = await db.execute(old_stmt)
            for old_p in old_result.scalars().all():
                if old_p.lat and old_p.lon:
                    old_coords[old_p.external_id] = (old_p.lat, old_p.lon)

            if old_coords:
                logger.info("sync_magnit_preserved_coords", count=len(old_coords))

            await db.execute(
                delete(PickupPointCache).where(PickupPointCache.provider == "magnit")
            )

            now = datetime.now(UTC)
            for idx, p in enumerate(points):
                lat = p.lat or 0.0
                lon = p.lon or 0.0

                # Apply geocoded coordinates
                if (not lat or not lon) and idx in geocoded:
                    lat, lon = geocoded[idx]

                # Fall back to previously cached coordinates
                if (not lat or not lon) and p.key in old_coords:
                    lat, lon = old_coords[p.key]

                # payment_method: ["already_paid", "postpay"]
                # "postpay" means COD is accepted (card only, no cash at Magnit PVZ)
                has_postpay = "postpay" in p.payment_method

                cache_entry = PickupPointCache(
                    provider="magnit",
                    external_id=p.key,
                    name=p.name,
                    point_type=p.type or "PVZ",
                    city=p.city or "",
                    full_address=p.address or "",
                    lat=lat,
                    lon=lon,
                    cash_allowed=False,
                    card_allowed=has_postpay,
                    raw_data=p.model_dump(by_alias=False),
                    synced_at=now,
                )
                db.add(cache_entry)

            await db.commit()

        logger.info("sync_magnit_points_completed", count=len(points), geocoded=len(geocoded))
    except Exception as e:
        logger.exception("sync_magnit_points_failed", error=str(e))
