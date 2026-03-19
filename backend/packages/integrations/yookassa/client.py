"""Async YooKassa payment client using httpx.

Uses the raw YooKassa REST API (https://api.yookassa.ru/v3), NOT the
``yookassa`` Python SDK.

Key features:
    - Basic auth (shop_id:secret_key).
    - Payment creation with receipt (54-FZ).
    - Payment status polling.
    - Payment cancellation.
    - Refund creation.
"""

from __future__ import annotations

from typing import Any

import httpx
import structlog

from packages.core.config import settings
from packages.core.exceptions import ProviderError
from packages.integrations.yookassa.models import (
    YooKassaAmount,
    YooKassaConfirmation,
    YooKassaPayment,
    YooKassaReceipt,
)

log = structlog.get_logger("integrations.yookassa")

_YOOKASSA_BASE_URL = "https://api.yookassa.ru/v3"

_instance: YooKassaClient | None = None


class YooKassaClient:
    """Async REST client for the YooKassa payment API."""

    def __init__(
        self,
        shop_id: str | None = None,
        secret_key: str | None = None,
        return_url: str | None = None,
    ) -> None:
        self.shop_id: str = shop_id or settings.yookassa_shop_id
        self.secret_key: str = secret_key or settings.yookassa_secret_key
        self.return_url: str = return_url or settings.effective_yookassa_return_url

        self._client: httpx.AsyncClient = httpx.AsyncClient(
            base_url=_YOOKASSA_BASE_URL,
            timeout=30.0,
            auth=(self.shop_id, self.secret_key),
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

    # ------------------------------------------------------------------
    # Generic request helper
    # ------------------------------------------------------------------

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict | None = None,
        idempotency_key: str | None = None,
    ) -> dict:
        """Execute an authenticated request to the YooKassa API."""
        headers: dict[str, str] = {}
        if idempotency_key:
            headers["Idempotence-Key"] = idempotency_key

        log.debug(
            "yookassa.request",
            method=method.upper(),
            path=path,
            has_idempotency_key=bool(idempotency_key),
        )

        try:
            response = await self._client.request(
                method=method,
                url=path,
                json=json_body,
                headers=headers,
            )
        except httpx.HTTPError as exc:
            raise ProviderError("yookassa", f"Network error: {exc}")

        log.debug("yookassa.response", status=response.status_code, path=path)

        if response.status_code >= 400:
            raise ProviderError(
                "yookassa",
                f"API error: HTTP {response.status_code} on {method.upper()} {path}",
                details={"body": response.text[:500]},
            )

        return response.json()

    # ------------------------------------------------------------------
    # Payments
    # ------------------------------------------------------------------

    async def create_payment(
        self,
        amount_rub: float,
        receipt: YooKassaReceipt | None = None,
        return_url: str | None = None,
        idempotency_key: str = "",
        description: str = "",
        confirmation_type: str = "redirect",
        metadata: dict[str, Any] | None = None,
    ) -> YooKassaPayment:
        """Create a new payment.

        Args:
            amount_rub: Payment amount in roubles (e.g. ``1500.00``).
            receipt: Optional 54-FZ receipt object.
            return_url: URL to redirect the customer after payment.
            idempotency_key: Unique key to prevent duplicate payments.
            description: Human-readable payment description.
            confirmation_type: ``"redirect"`` or ``"embedded"``.
            metadata: Arbitrary key-value data attached to the payment.

        Returns:
            A ``YooKassaPayment`` model with the created payment details.
        """
        body: dict[str, Any] = {
            "amount": {
                "value": f"{amount_rub:.2f}",
                "currency": "RUB",
            },
            "confirmation": {
                "type": confirmation_type,
                "return_url": return_url or self.return_url,
            },
            "capture": True,
        }

        if description:
            body["description"] = description

        if receipt:
            body["receipt"] = receipt.to_api_dict()

        if metadata:
            body["metadata"] = metadata

        log.info(
            "yookassa.create_payment",
            amount=amount_rub,
            description=description[:80] if description else "",
        )

        data = await self._request(
            "POST", "/payments", json_body=body, idempotency_key=idempotency_key
        )

        return self._parse_payment(data)

    async def get_payment(self, payment_id: str) -> YooKassaPayment:
        """Retrieve the current state of a payment by its ID."""
        log.info("yookassa.get_payment", payment_id=payment_id)
        data = await self._request("GET", f"/payments/{payment_id}")
        return self._parse_payment(data)

    async def cancel_payment(
        self, payment_id: str, idempotency_key: str = ""
    ) -> YooKassaPayment:
        """Cancel (void) a payment that has not yet been captured."""
        log.info("yookassa.cancel_payment", payment_id=payment_id)
        data = await self._request(
            "POST",
            f"/payments/{payment_id}/cancel",
            json_body={},
            idempotency_key=idempotency_key,
        )
        return self._parse_payment(data)

    # ------------------------------------------------------------------
    # Refunds
    # ------------------------------------------------------------------

    async def create_refund(
        self,
        payment_id: str,
        amount_rub: float,
        idempotency_key: str = "",
        description: str = "",
    ) -> dict:
        """Create a refund for a captured payment.

        Args:
            payment_id: The original payment ID to refund.
            amount_rub: Refund amount in roubles.
            idempotency_key: Unique key to prevent duplicate refunds.
            description: Optional refund description.

        Returns:
            The raw refund response dict from YooKassa.
        """
        body: dict[str, Any] = {
            "payment_id": payment_id,
            "amount": {
                "value": f"{amount_rub:.2f}",
                "currency": "RUB",
            },
        }
        if description:
            body["description"] = description

        log.info(
            "yookassa.create_refund",
            payment_id=payment_id,
            amount=amount_rub,
        )

        return await self._request(
            "POST", "/refunds", json_body=body, idempotency_key=idempotency_key
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_payment(data: dict) -> YooKassaPayment:
        """Parse raw API JSON into a ``YooKassaPayment`` model."""
        amount_data = data.get("amount")
        amount = (
            YooKassaAmount(
                value=str(amount_data.get("value", "0")),
                currency=amount_data.get("currency", "RUB"),
            )
            if amount_data
            else None
        )

        confirmation_data = data.get("confirmation")
        confirmation = None
        if confirmation_data:
            confirmation = YooKassaConfirmation(
                type=confirmation_data.get("type", ""),
                confirmation_url=confirmation_data.get("confirmation_url", ""),
            )

        return YooKassaPayment(
            id=data.get("id", ""),
            status=data.get("status", ""),
            amount=amount,
            confirmation=confirmation,
            description=data.get("description", ""),
            metadata=data.get("metadata", {}),
            paid=data.get("paid", False),
            refundable=data.get("refundable", False),
            created_at=data.get("created_at", ""),
        )


def get_client() -> YooKassaClient:
    """Return (or create) the module-level singleton client instance."""
    global _instance
    if _instance is None:
        _instance = YooKassaClient()
    return _instance
