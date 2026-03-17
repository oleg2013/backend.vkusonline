"""Contract tests for YooKassa API integration using respx mocks.

Validates that the YooKassaClient correctly calls the YooKassa REST API
and correctly parses the responses.
"""

from __future__ import annotations

import pytest
import respx
from httpx import Response

from packages.integrations.yookassa.client import YooKassaClient
from tests.fixtures.provider_payloads.yookassa import (
    PAYMENT_CANCELLED,
    PAYMENT_CREATED,
    PAYMENT_SUCCEEDED,
)


@pytest.fixture
def yookassa_client() -> YooKassaClient:
    return YooKassaClient(
        shop_id="test-shop-id",
        secret_key="test-secret-key",
        return_url="https://test.vkus.online/payment/return",
    )


class TestYooKassaCreatePayment:
    """Tests for YooKassaClient.create_payment."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_create_payment_returns_correct_structure(self, yookassa_client):
        respx.post("https://api.yookassa.ru/v3/payments").mock(
            return_value=Response(200, json=PAYMENT_CREATED)
        )

        payment = await yookassa_client.create_payment(
            amount_rub=1500.00,
            idempotency_key="test-key-001",
            description="Test payment",
        )

        assert payment.id == PAYMENT_CREATED["id"], (
            "payment ID should match the mock response"
        )
        assert payment.status == "pending", (
            "initial status should be 'pending'"
        )
        assert payment.amount is not None
        assert payment.amount.value == "1500.00"
        assert payment.amount.currency == "RUB"
        assert payment.confirmation is not None
        assert payment.confirmation.type == "redirect"
        assert "confirmation_url" in payment.confirmation.confirmation_url or len(
            payment.confirmation.confirmation_url
        ) > 0, "confirmation URL should be present"

    @pytest.mark.asyncio
    @respx.mock
    async def test_create_payment_sends_correct_headers(self, yookassa_client):
        route = respx.post("https://api.yookassa.ru/v3/payments").mock(
            return_value=Response(200, json=PAYMENT_CREATED)
        )

        await yookassa_client.create_payment(
            amount_rub=100.00,
            idempotency_key="header-test-key",
        )

        request = route.calls.last.request
        assert request.headers.get("Idempotence-Key") == "header-test-key", (
            "Idempotence-Key header should be set"
        )

    @pytest.mark.asyncio
    @respx.mock
    async def test_create_payment_metadata(self, yookassa_client):
        route = respx.post("https://api.yookassa.ru/v3/payments").mock(
            return_value=Response(200, json=PAYMENT_CREATED)
        )

        await yookassa_client.create_payment(
            amount_rub=100.00,
            idempotency_key="meta-key",
            metadata={"order_id": "ord-123"},
        )

        request = route.calls.last.request
        import json

        body = json.loads(request.content)
        assert body["metadata"]["order_id"] == "ord-123"


class TestYooKassaGetPayment:
    """Tests for YooKassaClient.get_payment."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_get_payment_returns_status(self, yookassa_client):
        payment_id = PAYMENT_SUCCEEDED["object"]["id"]
        respx.get(f"https://api.yookassa.ru/v3/payments/{payment_id}").mock(
            return_value=Response(200, json=PAYMENT_SUCCEEDED["object"])
        )

        payment = await yookassa_client.get_payment(payment_id)

        assert payment.id == payment_id
        assert payment.status == "succeeded"
        assert payment.paid is True


class TestYooKassaCancelPayment:
    """Tests for YooKassaClient.cancel_payment."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_cancel_payment_works(self, yookassa_client):
        payment_id = PAYMENT_CANCELLED["object"]["id"]
        respx.post(
            f"https://api.yookassa.ru/v3/payments/{payment_id}/cancel"
        ).mock(return_value=Response(200, json=PAYMENT_CANCELLED["object"]))

        payment = await yookassa_client.cancel_payment(
            payment_id, idempotency_key="cancel-key"
        )

        assert payment.id == payment_id
        assert payment.status == "canceled"
