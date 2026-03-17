from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from apps.api.deps import DbSession, RequestId
from packages.services import delivery as delivery_service
from packages.services.delivery.clustering import get_clustered_points

router = APIRouter(prefix="/delivery/5post", tags=["delivery-5post"])


@router.get("/pickup-points")
async def list_pickup_points(
    db: DbSession,
    request_id: RequestId,
    city: str | None = Query(None),
    lat: float | None = Query(None),
    lon: float | None = Query(None),
    limit: int = Query(50, le=5000),
):
    points = await delivery_service.search_pickup_points(
        db, provider="5post", city=city, lat=lat, lon=lon, limit=limit
    )
    return {"ok": True, "data": points, "request_id": request_id}


class ClusteredRequest(BaseModel):
    zoom: int = Field(..., ge=1, le=20)
    min_lat: float = Field(..., alias="minLat")
    max_lat: float = Field(..., alias="maxLat")
    min_lon: float = Field(..., alias="minLon")
    max_lon: float = Field(..., alias="maxLon")
    types: list[str] = Field(default_factory=list)
    cod_filter: bool = Field(default=False, alias="codFilter")

    model_config = {"populate_by_name": True}


@router.post("/clustered")
async def clustered_points(
    body: ClusteredRequest,
    db: DbSession,
    request_id: RequestId,
):
    """Server-side clustered pickup points for map viewport."""
    clusters = await get_clustered_points(
        db,
        provider="5post",
        zoom=body.zoom,
        min_lat=body.min_lat,
        min_lon=body.min_lon,
        max_lat=body.max_lat,
        max_lon=body.max_lon,
        types=body.types or None,
        cod_filter=body.cod_filter,
    )
    return {"ok": True, "data": {"clusters": clusters}, "request_id": request_id}


@router.post("/estimate")
async def estimate(
    db: DbSession,
    request_id: RequestId,
):
    # TODO: implement real estimate via 5Post rate calculation
    return {
        "ok": True,
        "data": {
            "provider": "5post",
            "estimated_cost": 0,
            "estimated_days_min": 2,
            "estimated_days_max": 7,
        },
        "request_id": request_id,
    }
