from __future__ import annotations

from fastapi import APIRouter

from apps.api.deps import DbSession, RequestId
from packages.core.config import settings
from packages.integrations.geo.dadata_client import DaDataClient
from packages.schemas.geo import CitySuggestRequest, HouseSuggestRequest, StreetSuggestRequest

router = APIRouter(prefix="/geo", tags=["geo"])

dadata = DaDataClient(
    api_key=settings.dadata_api_key,
    secret_key=settings.dadata_secret_key,
)


@router.post("/city-suggest")
async def city_suggest(body: CitySuggestRequest, request_id: RequestId):
    suggestions = await dadata.suggest_city(body.query)
    return {"ok": True, "data": {"suggestions": suggestions}, "request_id": request_id}


@router.post("/street-suggest")
async def street_suggest(body: StreetSuggestRequest, request_id: RequestId):
    suggestions = await dadata.suggest_street(body.city, body.query)
    return {"ok": True, "data": {"suggestions": suggestions}, "request_id": request_id}


@router.post("/house-suggest")
async def house_suggest(body: HouseSuggestRequest, request_id: RequestId):
    suggestions = await dadata.suggest_house(body.city, body.street, body.query)
    return {"ok": True, "data": {"suggestions": suggestions}, "request_id": request_id}
