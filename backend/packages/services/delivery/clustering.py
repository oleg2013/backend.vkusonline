"""Server-side geo clustering for pickup points.

Implements viewport-based clustering similar to 5Post widget:
- Client sends zoom level + bounding box
- Server groups points into grid cells based on zoom
- Returns clusters (with type counts) or individual points (high zoom)
"""

from __future__ import annotations

import math

from sqlalchemy import Float, String, case, cast, func, literal_column, select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.models.pickup_point import PickupPointCache


# Grid size in degrees per zoom level.
# detail_divisor controls density: higher = smaller grid = more clusters.
# divisor=1 → ~0.17° at zoom 11 (~20km, very coarse)
# divisor=4 → ~0.044° at zoom 11 (~5km, similar to 5Post widget)
def _grid_size(zoom: int, detail_divisor: int = 4) -> float:
    return 360.0 / (2 ** zoom) / max(detail_divisor, 1)


async def get_clustered_points(
    db: AsyncSession,
    provider: str,
    zoom: int,
    min_lat: float,
    min_lon: float,
    max_lat: float,
    max_lon: float,
    types: list[str] | None = None,
    cod_filter: bool = False,
) -> list[dict]:
    """Return clustered pickup points for a map viewport.

    At high zoom (>=15), returns individual points.
    At lower zoom, groups into grid cells with type counts.
    """
    # Base filter: provider + bounding box
    base_filter = [
        PickupPointCache.provider == provider,
        PickupPointCache.lat >= min_lat,
        PickupPointCache.lat <= max_lat,
        PickupPointCache.lon >= min_lon,
        PickupPointCache.lon <= max_lon,
        PickupPointCache.lat != 0,
        PickupPointCache.lon != 0,
    ]

    if types:
        base_filter.append(PickupPointCache.point_type.in_(types))

    if cod_filter:
        base_filter.append(
            (PickupPointCache.cash_allowed == True) | (PickupPointCache.card_allowed == True)  # noqa: E712
        )

    from packages.core.config import settings
    detail_divisor = settings.fivepost_map_cluster_detail

    # High zoom — return individual points
    if zoom >= 15:
        stmt = (
            select(
                PickupPointCache.external_id,
                PickupPointCache.name,
                PickupPointCache.point_type,
                PickupPointCache.city,
                PickupPointCache.full_address,
                PickupPointCache.lat,
                PickupPointCache.lon,
                PickupPointCache.cash_allowed,
                PickupPointCache.card_allowed,
                PickupPointCache.raw_data,
            )
            .where(*base_filter)
            .limit(500)
        )
        result = await db.execute(stmt)
        rows = result.all()

        clusters = []
        for r in rows:
            raw = r.raw_data or {}
            schedule = raw.get("work_schedule") or raw.get("work_hours") or []
            clusters.append({
                "lat": r.lat,
                "lon": r.lon,
                "data": {
                    "point": {
                        "id": r.external_id,
                        "name": r.name,
                        "type": r.point_type or "PVZ",
                        "city": r.city,
                        "fullAddress": r.full_address,
                        "cashAllowed": r.cash_allowed or False,
                        "cardAllowed": r.card_allowed or False,
                        "additional": raw.get("additional", ""),
                        "workSchedule": schedule,
                    }
                },
            })
        return clusters

    # Lower zoom — grid clustering
    grid = _grid_size(zoom, detail_divisor)

    # Grid cell keys for GROUP BY (not used as display coordinates)
    cell_key_lat = func.floor(PickupPointCache.lat / grid).label("cell_key_lat")
    cell_key_lon = func.floor(PickupPointCache.lon / grid).label("cell_key_lon")

    # Actual centroid of points in each cell
    avg_lat = func.avg(PickupPointCache.lat).label("avg_lat")
    avg_lon = func.avg(PickupPointCache.lon).label("avg_lon")

    # Count by type
    count_postamat = func.sum(
        case((PickupPointCache.point_type == "POSTAMAT", 1), else_=0)
    ).label("postamats")
    count_tobacco = func.sum(
        case((PickupPointCache.point_type.in_(["TOBACCO", "PARTNER_PICKUP"]), 1), else_=0)
    ).label("tobacco")
    count_pvz = func.sum(
        case((PickupPointCache.point_type.in_(["PVZ", "ISSUE_POINT"]), 1), else_=0)
    ).label("pvz")
    count_total = func.count().label("quantity")

    # Count COD-enabled
    count_cod = func.sum(
        case(
            ((PickupPointCache.cash_allowed == True) | (PickupPointCache.card_allowed == True), 1),  # noqa: E712
            else_=0,
        )
    ).label("cod_count")

    stmt = (
        select(cell_key_lat, cell_key_lon, avg_lat, avg_lon, count_total, count_postamat, count_tobacco, count_pvz, count_cod)
        .where(*base_filter)
        .group_by(literal_column("cell_key_lat"), literal_column("cell_key_lon"))
    )
    result = await db.execute(stmt)
    rows = result.all()

    clusters = []
    for r in rows:
        qty = r.quantity
        clusters.append({
            "lat": float(r.avg_lat),
            "lon": float(r.avg_lon),
            "data": {
                "postamats": r.postamats,
                "tobacco": r.tobacco,
                "pvz": r.pvz,
                "quantity": qty,
                "codCount": r.cod_count,
            },
            })

    return clusters
