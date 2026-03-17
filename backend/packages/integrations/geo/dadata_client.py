"""Async DaData Suggestions API client using httpx + Redis cache.

Ported from ``fivepost_cli/dadata_api.py`` and
``magnit_delivery/dadata_api.py``.  Provides address autocompletion
(city, street, house) and geocoding via the DaData REST API.

All network I/O is performed via ``httpx.AsyncClient``; no subprocess
calls are used.  Responses are cached in Redis to save the daily API
quota (10 000 req/day on the free plan).
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import httpx
import structlog

from packages.core.config import settings
from packages.core.exceptions import ProviderError

log = structlog.get_logger("integrations.dadata")

_DADATA_BASE_URL = "https://suggestions.dadata.ru/suggestions/api/4_1/rs"

# Cache TTLs (seconds)
_TTL_CITY_SUGGEST = 86400      # 24 h — cities almost never change
_TTL_STREET_SUGGEST = 86400    # 24 h
_TTL_HOUSE_SUGGEST = 86400     # 24 h
_TTL_GEOCODE = 7 * 86400       # 7 days — address coordinates are stable

_instance: DaDataClient | None = None


def _cache_key(prefix: str, body: dict) -> str:
    """Build a short Redis key from request body."""
    raw = json.dumps(body, sort_keys=True, ensure_ascii=False)
    digest = hashlib.md5(raw.encode()).hexdigest()[:12]
    return f"dadata:{prefix}:{digest}"


class DaDataClient:
    """Async client for the DaData Suggestions API with Redis caching."""

    def __init__(
        self,
        api_key: str | None = None,
        secret_key: str | None = None,
    ) -> None:
        self.api_key: str = api_key or settings.dadata_api_key
        self.secret_key: str = secret_key or settings.dadata_secret_key

        self._client: httpx.AsyncClient = httpx.AsyncClient(
            base_url=_DADATA_BASE_URL,
            timeout=15.0,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Authorization": f"Token {self.api_key}",
                "X-Secret": self.secret_key,
            },
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

    # ------------------------------------------------------------------
    # Redis cache helpers
    # ------------------------------------------------------------------

    @staticmethod
    async def _cache_get(key: str) -> list[dict] | None:
        """Try to read a cached response from Redis."""
        try:
            from packages.core.redis import redis_client
            raw = await redis_client.get(key)
            if raw:
                return json.loads(raw)
        except Exception:
            pass  # cache miss or Redis down — just call DaData
        return None

    @staticmethod
    async def _cache_set(key: str, data: list[dict], ttl: int) -> None:
        """Write a response to Redis with TTL."""
        try:
            from packages.core.redis import redis_client
            await redis_client.set(key, json.dumps(data, ensure_ascii=False), ex=ttl)
        except Exception:
            pass  # non-critical — next call will just hit DaData

    # ------------------------------------------------------------------
    # Generic request helper
    # ------------------------------------------------------------------

    async def _suggest(
        self, endpoint: str, body: dict, *, cache_prefix: str = "", cache_ttl: int = 0,
    ) -> list[dict]:
        """POST to a ``/suggest/*`` endpoint and return the suggestions list.

        When ``cache_prefix`` is set, checks Redis first and caches the
        response for ``cache_ttl`` seconds.
        """
        # --- cache lookup ---
        key = ""
        if cache_prefix and cache_ttl:
            key = _cache_key(cache_prefix, body)
            cached = await self._cache_get(key)
            if cached is not None:
                log.debug("dadata.cache_hit", prefix=cache_prefix, key=key)
                return cached

        # --- real API call ---
        log.debug("dadata.request", endpoint=endpoint)

        try:
            response = await self._client.post(endpoint, json=body)
        except httpx.HTTPError as exc:
            raise ProviderError("dadata", f"Network error: {exc}")

        if response.status_code != 200:
            raise ProviderError(
                "dadata",
                f"DaData HTTP {response.status_code}",
                details={"body": response.text[:500]},
            )

        data = response.json()
        suggestions = data.get("suggestions", [])
        log.debug("dadata.suggestions", count=len(suggestions))

        # --- cache store ---
        if key and suggestions:
            await self._cache_set(key, suggestions, cache_ttl)

        return suggestions

    # ------------------------------------------------------------------
    # City suggestions
    # ------------------------------------------------------------------

    async def suggest_city(self, query: str, count: int = 7) -> list[dict]:
        """Search for cities *and settlements* matching ``query``.

        Uses ``from_bound=city`` / ``to_bound=settlement`` so that
        villages (``с``), towns (``пгт``), hamlets (``д``) etc. are
        included alongside regular cities.

        Each returned dict contains the raw DaData suggestion plus
        an extra ``_clean_name`` key with the settlement-type prefix
        stripped (e.g. ``"Москва"`` instead of ``"г Москва"``).
        """
        body: dict[str, Any] = {
            "query": query,
            "count": count,
            "from_bound": {"value": "city"},
            "to_bound": {"value": "settlement"},
        }
        log.info("dadata.suggest_city", query=query)
        suggestions = await self._suggest(
            "/suggest/address", body,
            cache_prefix="city", cache_ttl=_TTL_CITY_SUGGEST,
        )

        # Enrich each suggestion with a clean city name
        for s in suggestions:
            data = s.get("data") or {}
            # DaData puts the name in data.city (for cities) or
            # data.settlement (for villages/towns/etc.)
            clean = data.get("city") or data.get("settlement") or s.get("value", "")
            s["_clean_name"] = clean
            # Also include coordinates at top level for convenience
            s["_geo_lat"] = data.get("geo_lat")
            s["_geo_lon"] = data.get("geo_lon")

        return suggestions

    # ------------------------------------------------------------------
    # Street suggestions
    # ------------------------------------------------------------------

    async def suggest_street(
        self, city: str, query: str, count: int = 5
    ) -> list[dict]:
        """Search for streets within a city.

        ``city`` should be the ``city_fias_id`` obtained from
        ``suggest_city``.
        """
        body: dict[str, Any] = {
            "query": query,
            "count": count,
            "from_bound": {"value": "street"},
            "to_bound": {"value": "street"},
            "locations": [{"city_fias_id": city}],
        }
        log.info("dadata.suggest_street", query=query, city_fias_id=city)
        return await self._suggest(
            "/suggest/address", body,
            cache_prefix="street", cache_ttl=_TTL_STREET_SUGGEST,
        )

    # ------------------------------------------------------------------
    # House suggestions
    # ------------------------------------------------------------------

    async def suggest_house(
        self, city: str, street: str, query: str, count: int = 5
    ) -> list[dict]:
        """Search for house numbers on a street.

        ``city`` is the ``city_fias_id``; ``street`` is the
        ``street_fias_id`` obtained from ``suggest_street``.

        Results include geocoded coordinates in ``data.geo_lat`` /
        ``data.geo_lon``.
        """
        body: dict[str, Any] = {
            "query": query,
            "count": count,
            "from_bound": {"value": "house"},
            "to_bound": {"value": "house"},
            "locations": [{"street_fias_id": street}],
        }
        log.info(
            "dadata.suggest_house",
            query=query,
            city_fias_id=city,
            street_fias_id=street,
        )
        return await self._suggest(
            "/suggest/address", body,
            cache_prefix="house", cache_ttl=_TTL_HOUSE_SUGGEST,
        )

    # ------------------------------------------------------------------
    # Geocoding
    # ------------------------------------------------------------------

    async def geocode_address(self, address: str) -> tuple[float, float] | None:
        """Geocode a free-form address string.

        Returns ``(lat, lon)`` if coordinates are found, or ``None``.
        """
        body: dict[str, Any] = {
            "query": address,
            "count": 1,
        }
        log.info("dadata.geocode_address", address=address[:80])
        suggestions = await self._suggest(
            "/suggest/address", body,
            cache_prefix="geocode", cache_ttl=_TTL_GEOCODE,
        )

        if not suggestions:
            return None

        data = suggestions[0].get("data", {})
        geo_lat = data.get("geo_lat")
        geo_lon = data.get("geo_lon")

        if geo_lat and geo_lon:
            try:
                return float(geo_lat), float(geo_lon)
            except (ValueError, TypeError):
                return None

        return None


def get_client() -> DaDataClient:
    """Return (or create) the module-level singleton client instance."""
    global _instance
    if _instance is None:
        _instance = DaDataClient()
    return _instance
