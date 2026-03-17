from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import structlog

from packages.core.db import async_session_factory
from packages.integrations.fivepost.client import get_client
from packages.models.pickup_point import PickupPointCache

logger = structlog.get_logger(__name__)

# Directory for saving original API responses for debugging
_PVZ_CACHE_DIR = Path("data/pvz_cache")


async def sync_fivepost_points() -> None:
    logger.info("sync_5post_points_started")
    try:
        client = get_client()
        points = await client.get_all_pickup_points()
        logger.info("sync_5post_fetched", count=len(points))

        # --- Save original API response as JSON for debugging -----------
        try:
            _PVZ_CACHE_DIR.mkdir(parents=True, exist_ok=True)
            cache_file = _PVZ_CACHE_DIR / "5post_pickup_points.json"
            raw_list = [p.model_dump() for p in points]
            cache_file.write_text(
                json.dumps(raw_list, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            size_mb = cache_file.stat().st_size / (1024 * 1024)
            logger.info(
                "sync_5post_json_saved",
                path=str(cache_file),
                size_mb=round(size_mb, 2),
                count=len(raw_list),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("sync_5post_json_save_failed", error=str(exc))

        async with async_session_factory() as db:
            # Delete old cache
            from sqlalchemy import delete

            await db.execute(
                delete(PickupPointCache).where(PickupPointCache.provider == "5post")
            )

            now = datetime.now(UTC)
            for p in points:
                cache_entry = PickupPointCache(
                    provider="5post",
                    external_id=p.id,
                    name=p.name,
                    point_type=p.type,
                    city=p.city or "",
                    full_address=p.full_address,
                    lat=p.lat,
                    lon=p.lng,
                    cash_allowed=p.cash_allowed,
                    card_allowed=p.card_allowed,
                    rates={
                        "rates": [r.model_dump() for r in p.rates] if p.rates else []
                    },
                    cell_limits=p.cell_limits.model_dump() if p.cell_limits else None,
                    raw_data=p.model_dump(),
                    synced_at=now,
                )
                db.add(cache_entry)

            await db.commit()

        logger.info("sync_5post_points_completed", count=len(points))
    except Exception as e:
        logger.exception("sync_5post_points_failed", error=str(e))
