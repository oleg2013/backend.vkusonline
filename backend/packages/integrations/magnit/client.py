"""Async Magnit Post API client using httpx.

Ported from ``magnit_delivery/magnit_api.py``.  All network I/O is
performed via ``httpx.AsyncClient``; no subprocess calls are used.

Key features:
    - OAuth2 ``client_credentials`` flow with in-memory token caching.
    - Paginated pickup-point loading.
    - Order creation (V2 API) / cancellation / status.
    - Delivery cost estimation.
    - Shipping label download.
"""

from __future__ import annotations

import time
from typing import Any

import httpx
import structlog

from packages.core.config import settings
from packages.core.exceptions import ProviderError
from packages.integrations.magnit.models import (
    MagnitEstimate,
    MagnitOrder,
    MagnitPickupPoint,
    MagnitWorkSchedule,
)

log = structlog.get_logger("integrations.magnit")

_instance: MagnitClient | None = None


class MagnitClient:
    """Async REST client for the Magnit Post API."""

    def __init__(
        self,
        base_url: str | None = None,
        client_id: str | None = None,
        client_secret: str | None = None,
        warehouse_uuid: str | None = None,
    ) -> None:
        self.base_url: str = (base_url or settings.magnit_base_url).rstrip("/")
        self.client_id: str = client_id or settings.magnit_client_id
        self.client_secret: str = client_secret or settings.magnit_client_secret
        self.warehouse_uuid: str = warehouse_uuid or settings.magnit_warehouse_uuid

        self._client: httpx.AsyncClient = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=60.0,
            headers={"Accept": "application/json"},
        )

        # OAuth2 token state
        self._access_token: str | None = None
        self._token_expires_at: float = 0.0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

    # ------------------------------------------------------------------
    # OAuth2 authentication
    # ------------------------------------------------------------------

    async def _authenticate(self) -> str:
        """Obtain an OAuth2 access token via the client_credentials grant.

        The token is cached in memory and automatically refreshed
        60 seconds before expiry.
        """
        if self._access_token and time.time() < self._token_expires_at - 60:
            return self._access_token

        url = "/api/v2/oauth/token"
        payload = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "scope": "openid",
            "grant_type": "client_credentials",
        }

        log.info("magnit.oauth_request", url=url)

        try:
            response = await self._client.post(
                url,
                data=payload,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        except httpx.HTTPError as exc:
            raise ProviderError("magnit", f"Network error during OAuth: {exc}")

        if response.status_code != 200:
            raise ProviderError(
                "magnit",
                f"OAuth failed: HTTP {response.status_code}",
                details={"body": response.text[:500]},
            )

        data = response.json()
        self._access_token = data.get("access_token")
        expires_in = data.get("expires_in", 3600)
        self._token_expires_at = time.time() + expires_in

        log.info("magnit.oauth_token_obtained", expires_in=expires_in)
        return self._access_token  # type: ignore[return-value]

    async def _auth_headers(self) -> dict[str, str]:
        """Return headers containing a valid Bearer token."""
        token = await self._authenticate()
        return {"Authorization": f"Bearer {token}"}

    # ------------------------------------------------------------------
    # Generic request helper
    # ------------------------------------------------------------------

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict | list | None = None,
    ) -> Any:
        """Execute an authenticated HTTP request to the Magnit API."""
        headers = await self._auth_headers()

        log.debug("magnit.request", method=method.upper(), path=path, params=params)

        try:
            response = await self._client.request(
                method=method,
                url=path,
                params=params,
                json=json_body,
                headers=headers,
            )
        except httpx.HTTPError as exc:
            raise ProviderError("magnit", f"Network error: {exc}")

        log.debug("magnit.response", status=response.status_code, path=path)

        if response.status_code >= 400:
            body_text = response.text[:500]
            log.error("magnit.api_error", status=response.status_code, path=path, body=body_text)
            raise ProviderError(
                "magnit",
                f"HTTP {response.status_code}: {body_text}",
                details={"body": body_text},
            )

        if response.status_code == 204:
            return {}

        return response.json()

    async def _request_raw(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> bytes:
        """Execute a request and return raw response bytes."""
        headers = await self._auth_headers()
        headers["Accept"] = "*/*"

        try:
            response = await self._client.request(
                method=method, url=path, headers=headers, params=params
            )
        except httpx.HTTPError as exc:
            raise ProviderError("magnit", f"Network error: {exc}")

        if response.status_code >= 400:
            body_text = response.text[:500]
            log.error("magnit.api_error", status=response.status_code, path=path, body=body_text)
            raise ProviderError(
                "magnit",
                f"HTTP {response.status_code}: {body_text}",
                details={"body": body_text},
            )

        return response.content

    # ------------------------------------------------------------------
    # Pickup points
    # ------------------------------------------------------------------

    async def get_pickup_points(
        self,
        city: str | None = None,
        region: str | None = None,
        page_size: int = 1000,
    ) -> list[MagnitPickupPoint]:
        """Fetch pickup points with optional city/region filtering.

        Automatically paginates through all available pages.
        """
        log.info("magnit.load_pickup_points", city=city, region=region)
        all_points: list[MagnitPickupPoint] = []
        current_page = 1

        while True:
            params: dict[str, Any] = {"page": current_page, "size": page_size}
            if city:
                params["city"] = city
            if region:
                params["region"] = region

            data = await self._request(
                "GET", "/api/v1/magnit-post/pickup-points", params=params
            )

            # The API may return a list or a paginated wrapper object.
            if isinstance(data, list):
                points_raw = data
            elif isinstance(data, dict):
                points_raw = data.get(
                    "items",
                    data.get("pickupPoints", data.get("pickup_points", [])),
                )
            else:
                points_raw = []

            for item in points_raw:
                all_points.append(self._parse_pickup_point(item))

            log.debug(
                "magnit.pickup_points_page",
                page=current_page,
                count=len(points_raw),
            )

            if len(points_raw) < page_size:
                break
            current_page += 1

        log.info("magnit.pickup_points_loaded", count=len(all_points))
        return all_points

    @staticmethod
    def _parse_pickup_point(item: dict) -> MagnitPickupPoint:
        """Parse a pickup point from the raw API JSON.

        Magnit API returns workHours with from/till keys:
          {"day": "MON", "from": "08:30", "till": "22:30"}
        """
        schedule_raw = (
            item.get("workHours")
            or item.get("work_hours")
            or item.get("work_schedule")
            or item.get("workSchedule")
            or []
        )
        schedule: list[MagnitWorkSchedule] = []
        if isinstance(schedule_raw, list):
            for entry in schedule_raw:
                schedule.append(
                    MagnitWorkSchedule(
                        day=entry.get("day", ""),
                        opens_at=entry.get("from", entry.get("opens_at", entry.get("opensAt", ""))),
                        closes_at=entry.get("till", entry.get("closes_at", entry.get("closesAt", ""))),
                    )
                )

        # Coordinates may be at top-level (lat/lon, latitude/longitude)
        # or nested inside a "coordinates" object: {"latitude": ..., "longitude": ...}
        coords = item.get("coordinates") or {}
        lat = (
            item.get("lat")
            or item.get("latitude")
            or (coords.get("latitude") if isinstance(coords, dict) else None)
        )
        lon = (
            item.get("lon")
            or item.get("longitude")
            or (coords.get("longitude") if isinstance(coords, dict) else None)
        )

        payment_methods = item.get("payment_method") or item.get("paymentMethod") or []
        if isinstance(payment_methods, str):
            payment_methods = [payment_methods]

        return MagnitPickupPoint(
            key=item.get("key", item.get("pickup_point_key", "")),
            name=item.get("name", item.get("pickup_point_name", "")).replace("%", " "),
            city=item.get("city", ""),
            address=item.get("address", ""),
            lat=lat,
            lon=lon,
            work_schedule=schedule,
            payment_method=payment_methods,
            region=item.get("region", ""),
            status=item.get("status", ""),
            type=item.get("type", ""),
        )

    # ------------------------------------------------------------------
    # Order operations
    # ------------------------------------------------------------------

    async def create_order(self, order: MagnitOrder) -> dict:
        """Create a new order via the Magnit V2 API.

        The ``pickup_point`` field must be provided as ``{"key": "..."}``
        in the order model.
        """
        log.info(
            "magnit.create_order",
            customer_order_id=order.customer_order_id,
            warehouse_uuid=order.warehouse_uuid,
        )

        result = await self._request(
            "POST",
            "/api/v2/magnit-post/orders",
            json_body=order.to_api_dict(),
        )

        log.info("magnit.order_created", result_keys=list(result.keys()) if isinstance(result, dict) else "non-dict")
        return result

    async def get_order_status(self, order_id: str) -> dict:
        """Get the current status and details for an order.

        ``order_id`` is the Magnit-assigned order UUID.
        """
        log.info("magnit.get_order_status", order_id=order_id)
        return await self._request("GET", f"/api/v2/magnit-post/orders/{order_id}")

    async def cancel_order(self, order_id: str) -> dict:
        """Cancel an order by its Magnit UUID."""
        log.info("magnit.cancel_order", order_id=order_id)
        return await self._request("DELETE", f"/api/v1/magnit-post/orders/{order_id}")

    async def get_label(self, order_id: str) -> bytes:
        """Download the shipping label (PDF) for an order.

        Returns the raw bytes of the label document.
        """
        log.info("magnit.get_label", order_id=order_id)
        return await self._request_raw(
            "GET", f"/api/v1/magnit-post/orders/{order_id}/label"
        )

    # ------------------------------------------------------------------
    # Delivery estimation
    # ------------------------------------------------------------------

    async def estimate_delivery(
        self,
        from_city: str,
        to_city: str | None = None,
        pickup_point_key: str | None = None,
        parcel_size: str | None = None,
    ) -> MagnitEstimate:
        """Estimate delivery cost and time.

        Either ``to_city`` or ``pickup_point_key`` must be provided.
        """
        body: dict[str, Any] = {"city_from": from_city}
        if pickup_point_key:
            body["pickup_point_key"] = pickup_point_key
        if to_city:
            body["city"] = to_city

        log.info(
            "magnit.estimate_delivery",
            from_city=from_city,
            to_city=to_city,
            pickup_point_key=pickup_point_key,
        )

        data = await self._request(
            "POST", "/api/v2/magnit-post/orders/estimate", json_body=body
        )

        return MagnitEstimate(
            delivery_cost=float(data.get("delivery_cost", data.get("deliveryCost", 0))),
            delivery_days_min=int(data.get("delivery_days_min", data.get("deliveryDaysMin", 0))),
            delivery_days_max=int(data.get("delivery_days_max", data.get("deliveryDaysMax", 0))),
            pickup_point_key=pickup_point_key or "",
        )


def get_client() -> MagnitClient:
    """Return (or create) the module-level singleton client instance."""
    global _instance
    if _instance is None:
        _instance = MagnitClient()
    return _instance
