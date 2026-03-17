from __future__ import annotations

from fastapi import APIRouter, Query

from apps.api.deps import DbSession, RequestId
from packages.services import delivery as delivery_service

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
