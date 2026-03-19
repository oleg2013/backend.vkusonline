from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from apps.api.deps import DbSession, RequestId
from packages.services import delivery as delivery_service
from packages.services.delivery.clustering import get_clustered_points

router = APIRouter(prefix="/delivery/magnit", tags=["delivery-magnit"])


@router.get("/cities")
async def list_cities(db: DbSession, request_id: RequestId):
    cities = await delivery_service.get_magnit_cities(db)
    return {"ok": True, "data": cities, "request_id": request_id}


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
        db, provider="magnit", city=city, lat=lat, lon=lon, limit=limit
    )
    return {"ok": True, "data": points, "request_id": request_id}


@router.get("/nearest-cities")
async def nearest_cities(
    lat: float,
    lon: float,
    db: DbSession,
    request_id: RequestId,
    limit: int = Query(5, le=20),
):
    cities = await delivery_service.find_nearest_magnit_cities(db, lat, lon, limit)
    return {"ok": True, "data": cities, "request_id": request_id}


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
        provider="magnit",
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
    # TODO: implement real estimate via Magnit API
    return {
        "ok": True,
        "data": {
            "provider": "magnit",
            "estimated_cost": 183.0,
            "estimated_days_min": 3,
            "estimated_days_max": 7,
        },
        "request_id": request_id,
    }
