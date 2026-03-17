"""Async 5Post API client using httpx.

Ported from ``fivepost_cli/fivepost_api.py``.  All network I/O is
performed via ``httpx.AsyncClient``; no subprocess calls are used.

Key features:
    - JWT authentication with in-memory token caching (1 hour validity,
      auto-refresh 5 minutes before expiry).
    - Paginated pickup-point loading.
    - Order creation / cancellation / status / label retrieval.
    - Delivery cost calculation.
"""

from __future__ import annotations

import asyncio
import base64
import json
import time
from typing import Any

import httpx
import structlog

from packages.core.config import settings
from packages.core.exceptions import ProviderError
from packages.integrations.fivepost.models import (
    FivePostCellLimits,
    FivePostOrder,
    FivePostPickupPoint,
    FivePostRate,
    FivePostStatus,
    FivePostTrackingEvent,
    FivePostWorkHours,
)
from packages.integrations.fivepost.utils import (
    _get_best_rate,
    calculate_delivery_cost,
)

log = structlog.get_logger("integrations.fivepost")

# Page size when fetching pickup points (API maximum is 1000).
_PICKUP_POINTS_PAGE_SIZE: int = 1000
# Delay between paginated requests (seconds).
_INTER_PAGE_DELAY: float = 0.5

_instance: FivePostClient | None = None


class FivePostClient:
    """Async REST client for the 5Post delivery API."""

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        warehouse_id: str | None = None,
    ) -> None:
        self.base_url: str = (base_url or settings.fivepost_base_url).rstrip("/")
        self.api_key: str = api_key or settings.fivepost_api_key
        self.warehouse_id: str = warehouse_id or settings.fivepost_warehouse_id

        self._client: httpx.AsyncClient = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=60.0,
            headers={"Accept": "application/json"},
        )

        # JWT token state
        self._jwt_token: str | None = None
        self._jwt_expires_at: float = 0.0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

    # ------------------------------------------------------------------
    # JWT authentication
    # ------------------------------------------------------------------

    @staticmethod
    def _decode_jwt_exp(token: str) -> float:
        """Extract the ``exp`` claim from a JWT without external libraries."""
        try:
            parts = token.split(".")
            if len(parts) != 3:
                return 0.0
            payload_b64 = parts[1]
            padding = 4 - len(payload_b64) % 4
            if padding != 4:
                payload_b64 += "=" * padding
            payload = json.loads(base64.urlsafe_b64decode(payload_b64))
            return float(payload.get("exp", 0))
        except Exception:
            return 0.0

    def _is_token_valid(self) -> bool:
        """Return ``True`` if the cached JWT is still valid (5 min margin)."""
        if not self._jwt_token:
            return False
        return time.time() < (self._jwt_expires_at - 300)

    async def _ensure_token(self) -> None:
        """Obtain or refresh the JWT token when necessary."""
        if not self._is_token_valid():
            await self._refresh_token()

    async def _refresh_token(self) -> None:
        """Request a new JWT from the 5Post API."""
        url = "/jwt-generate-claims/rs256/1"
        params = {"apikey": self.api_key}
        headers = {"content-type": "application/x-www-form-urlencoded"}
        data = "subject=OpenAPI&audience=A122019!"

        log.info("fivepost.jwt_refresh", url=url)

        try:
            response = await self._client.post(
                url, params=params, headers=headers, content=data
            )
        except httpx.HTTPError as exc:
            raise ProviderError("5post", f"Network error while obtaining JWT: {exc}")

        if response.status_code == 401:
            raise ProviderError(
                "5post",
                "Authentication failed (401) while obtaining JWT",
                details={"body": response.text[:500]},
            )

        if response.status_code >= 400:
            raise ProviderError(
                "5post",
                f"JWT request failed with HTTP {response.status_code}",
                details={"body": response.text[:500]},
            )

        result = response.json()
        if result.get("status") == "ok" and "jwt" in result:
            self._jwt_token = result["jwt"]
            self._jwt_expires_at = self._decode_jwt_exp(self._jwt_token)
            log.info("fivepost.jwt_obtained", expires_at=self._jwt_expires_at)
        else:
            raise ProviderError(
                "5post",
                "Unexpected JWT response",
                details={"body": result},
            )

    async def _auth_headers(self) -> dict[str, str]:
        """Return headers with a valid Bearer token."""
        await self._ensure_token()
        return {
            "authorization": f"Bearer {self._jwt_token}",
            "content-type": "application/json",
        }

    # ------------------------------------------------------------------
    # Generic request helper
    # ------------------------------------------------------------------

    async def _request(
        self,
        method: str,
        endpoint: str,
        *,
        json_data: dict | list | None = None,
        params: dict[str, Any] | None = None,
        retry_on_401: bool = True,
    ) -> Any:
        """Execute an authenticated API request.

        Automatically retries once on 401 after refreshing the JWT.
        """
        headers = await self._auth_headers()

        log.debug(
            "fivepost.request",
            method=method.upper(),
            endpoint=endpoint,
            params=params,
        )

        try:
            response = await self._client.request(
                method=method,
                url=endpoint,
                headers=headers,
                json=json_data,
                params=params,
            )
        except httpx.HTTPError as exc:
            raise ProviderError("5post", f"Network error: {exc}")

        log.debug("fivepost.response", status=response.status_code)

        if response.status_code == 401 and retry_on_401:
            log.warning("fivepost.401_retry")
            await self._refresh_token()
            return await self._request(
                method, endpoint, json_data=json_data, params=params, retry_on_401=False
            )

        if response.status_code == 429:
            raise ProviderError(
                "5post",
                "Rate limit exceeded (429)",
                details={"body": response.text[:500]},
            )

        if response.status_code >= 400:
            raise ProviderError(
                "5post",
                f"API error: HTTP {response.status_code} on {method.upper()} {endpoint}",
                details={"body": response.text[:500]},
            )

        return response.json()

    async def _request_raw(
        self,
        method: str,
        endpoint: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> bytes:
        """Execute a request and return the raw response bytes (e.g. PDF label)."""
        headers = await self._auth_headers()
        # Accept any content type for binary responses.
        headers["accept"] = "*/*"

        try:
            response = await self._client.request(
                method=method, url=endpoint, headers=headers, params=params
            )
        except httpx.HTTPError as exc:
            raise ProviderError("5post", f"Network error: {exc}")

        if response.status_code >= 400:
            raise ProviderError(
                "5post",
                f"API error: HTTP {response.status_code} on {method.upper()} {endpoint}",
                details={"body": response.text[:500]},
            )

        return response.content

    # ------------------------------------------------------------------
    # Pickup points
    # ------------------------------------------------------------------

    async def get_all_pickup_points(self) -> list[FivePostPickupPoint]:
        """Fetch all active pickup points with pagination.

        Returns a list of ``FivePostPickupPoint`` models.
        """
        log.info("fivepost.load_pickup_points")
        all_points: list[FivePostPickupPoint] = []
        page = 0
        total_pages = 1

        while page < total_pages:
            body = {"pageSize": _PICKUP_POINTS_PAGE_SIZE, "pageNumber": page}

            try:
                data = await self._request(
                    "POST", "/api/v1/pickuppoints/query", json_data=body
                )
            except ProviderError as exc:
                if "429" in exc.message:
                    log.warning(
                        "fivepost.rate_limit_during_pickup_points",
                        loaded=len(all_points),
                        page=page,
                    )
                    break
                raise

            total_pages = data.get("totalPages", 1)
            content = data.get("content", [])

            if page == 0:
                log.info(
                    "fivepost.pickup_points_total",
                    total_elements=data.get("totalElements", 0),
                    total_pages=total_pages,
                )

            for item in content:
                point = self._parse_pickup_point(item)
                if point is not None:
                    all_points.append(point)

            page += 1
            if page < total_pages:
                await asyncio.sleep(_INTER_PAGE_DELAY)

        log.info("fivepost.pickup_points_loaded", count=len(all_points))
        return all_points

    @staticmethod
    def _parse_pickup_point(item: dict) -> FivePostPickupPoint | None:
        """Parse a single pickup point from the raw API JSON."""
        try:
            address = item.get("address", {})

            rates: list[FivePostRate] = []
            for r in item.get("rate", []):
                rates.append(
                    FivePostRate(
                        rate_type=r.get("rateType", ""),
                        rate_value=float(r.get("rateValue", 0)),
                        rate_value_with_vat=float(r.get("rateValueWithVat", 0)),
                        rate_extra_value=float(r.get("rateExtraValue", 0)),
                        rate_extra_value_with_vat=float(r.get("rateExtraValueWithVat", 0)),
                        zone=str(r.get("zone", "")),
                        currency=r.get("rateCurrency", "RUB"),
                        vat=int(r.get("vat", 0)),
                    )
                )

            cl = item.get("cellLimits", {})
            cell_limits = FivePostCellLimits(
                max_width_mm=int(cl.get("maxCellWidth", 0)),
                max_height_mm=int(cl.get("maxCellHeight", 0)),
                max_length_mm=int(cl.get("maxCellLength", 0)),
                max_weight_mg=int(cl.get("maxWeight", 0)),
            )

            day_order = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
            raw_hours = item.get("workHours", [])
            raw_hours_sorted = sorted(
                raw_hours,
                key=lambda wh: (
                    day_order.index(wh.get("day", "MON"))
                    if wh.get("day") in day_order
                    else 99
                ),
            )
            work_hours = [
                FivePostWorkHours(
                    day=wh.get("day", ""),
                    opens_at=wh.get("opensAt", ""),
                    closes_at=wh.get("closesAt", ""),
                )
                for wh in raw_hours_sorted
            ]

            return FivePostPickupPoint(
                id=item.get("id", ""),
                name=item.get("name", ""),
                type=item.get("type", ""),
                full_address=item.get("fullAddress", ""),
                city=address.get("city", ""),
                lat=float(address.get("lat", 0)),
                lng=float(address.get("lng", 0)),
                cash_allowed=bool(item.get("cashAllowed", False)),
                card_allowed=bool(item.get("cardAllowed", False)),
                rates=rates,
                cell_limits=cell_limits,
                additional=item.get("additional", ""),
                work_hours=work_hours,
                phone=item.get("phone", ""),
                short_address=item.get("shortAddress", ""),
                partner_name=item.get("partnerName", ""),
                mdm_code=item.get("mdmCode", ""),
            )
        except (ValueError, TypeError, KeyError) as exc:
            log.warning("fivepost.parse_pickup_point_error", error=str(exc))
            return None

    # ------------------------------------------------------------------
    # Order operations
    # ------------------------------------------------------------------

    async def create_order(self, order: FivePostOrder) -> dict:
        """Create a new order via the 5Post API v3.

        Returns the first element of the response array (order result).
        """
        log.info("fivepost.create_order", sender_order_id=order.sender_order_id)

        result = await self._request(
            "POST", "/api/v3/orders", json_data=order.to_api_dict()
        )

        if isinstance(result, list) and len(result) > 0:
            order_result = result[0]
            if order_result.get("created"):
                log.info(
                    "fivepost.order_created",
                    order_id=order_result.get("orderId"),
                    sender_order_id=order_result.get("senderOrderId"),
                )
            else:
                errors = order_result.get("errors", [])
                log.error("fivepost.order_creation_failed", errors=errors)
            return order_result

        log.error("fivepost.unexpected_response_format", result=result)
        return {"created": False, "errors": [{"text": f"Unexpected response: {result}"}]}

    async def get_order_status(self, order_id: str) -> FivePostStatus:
        """Get the current status and tracking history for an order.

        ``order_id`` is the 5Post-assigned order UUID.
        """
        log.info("fivepost.get_order_status", order_id=order_id)
        data = await self._request("GET", f"/api/v1/orders/{order_id}/status")

        events: list[FivePostTrackingEvent] = []
        for ev in data.get("trackingEvents", data.get("statusHistory", [])):
            events.append(
                FivePostTrackingEvent(
                    status_code=ev.get("statusCode", ev.get("status", "")),
                    status_name=ev.get("statusName", ev.get("statusTitle", "")),
                    timestamp=ev.get("timestamp", ev.get("dateTime", "")),
                    description=ev.get("description", ""),
                )
            )

        return FivePostStatus(
            order_id=data.get("orderId", order_id),
            sender_order_id=data.get("senderOrderId", ""),
            status_code=data.get("statusCode", data.get("status", "")),
            status_name=data.get("statusName", data.get("statusTitle", "")),
            tracking_events=events,
        )

    async def cancel_order(self, order_id: str) -> dict:
        """Cancel an order by its 5Post UUID."""
        log.info("fivepost.cancel_order", order_id=order_id)
        return await self._request("DELETE", f"/api/v1/orders/{order_id}")

    async def get_label(self, order_id: str) -> bytes:
        """Download the shipping label (PDF) for an order.

        Returns the raw bytes of the PDF document.
        """
        log.info("fivepost.get_label", order_id=order_id)
        return await self._request_raw("GET", f"/api/v1/orders/{order_id}/label")

    # ------------------------------------------------------------------
    # Rate calculation
    # ------------------------------------------------------------------

    async def calculate_rate(
        self, point: FivePostPickupPoint, weight_mg: int
    ) -> float:
        """Calculate the delivery cost for a given pickup point and weight.

        Uses the best (cheapest) rate available for the point.
        Returns cost in roubles, or 0.0 if no valid rate exists.
        """
        rate = _get_best_rate(point)
        if rate is None:
            return 0.0
        return calculate_delivery_cost(rate, weight_mg)


def get_client() -> FivePostClient:
    """Return (or create) the module-level singleton client instance."""
    global _instance
    if _instance is None:
        _instance = FivePostClient()
    return _instance
