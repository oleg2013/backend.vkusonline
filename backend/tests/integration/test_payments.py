"""Integration tests for the payments service."""

from __future__ import annotations

import pytest

from packages.core.exceptions import ConflictError
from packages.enums import OrderStatus, PaymentStatus
from packages.services.checkout import create_order, update_order_status
from packages.services.payments import (
    create_payment,
    process_payment_success,
    update_payment_from_provider,
)


async def _create_test_order(db_session, sample_product, **kwargs):
    """Helper to create a test order."""
    defaults = dict(
        items=[{"sku": sample_product.sku, "quantity": 1}],
        customer_email="pay@example.com",
        customer_phone="+79991234567",
        customer_name="Pay Customer",
        delivery_provider="5post",
        delivery_city="Moscow",
        delivery_address=None,
        pickup_point_id="pp-pay",
        pickup_point_name="Payment Point",
        customer_delivery_price=20000,
        carrier_estimated_cost=15000,
    )
    defaults.update(kwargs)
    return await create_order(db_session, **defaults)


class TestCreatePayment:
    """Tests for create_payment."""

    @pytest.mark.asyncio
    async def test_create_payment_for_valid_order(self, db_session, sample_product):
        order = await _create_test_order(db_session, sample_product)

        payment = await create_payment(
            db_session, order, idempotency_key="pay-key-001"
        )

        assert payment is not None, "create_payment should return a payment"
        assert payment.order_id == order.id
        assert payment.status == PaymentStatus.PENDING
        assert payment.amount == order.total
        assert payment.provider == "yookassa"
        assert payment.idempotency_key == "pay-key-001"

    @pytest.mark.asyncio
    async def test_duplicate_idempotency_key_returns_same_payment(
        self, db_session, sample_product
    ):
        order = await _create_test_order(db_session, sample_product)

        payment1 = await create_payment(
            db_session, order, idempotency_key="dup-pay-key"
        )
        payment2 = await create_payment(
            db_session, order, idempotency_key="dup-pay-key"
        )

        assert payment1.id == payment2.id, (
            "same idempotency key should return the same payment"
        )

    @pytest.mark.asyncio
    async def test_create_payment_wrong_status_fails(self, db_session, sample_product):
        order = await _create_test_order(db_session, sample_product)

        # Move order to PAID status (not PENDING_PAYMENT)
        await update_order_status(db_session, order, OrderStatus.PAID)

        with pytest.raises(ConflictError, match="Cannot create payment"):
            await create_payment(
                db_session, order, idempotency_key="wrong-status-key"
            )

    @pytest.mark.asyncio
    async def test_create_payment_cancelled_order_fails(self, db_session, sample_product):
        order = await _create_test_order(db_session, sample_product)

        # Cancel the order
        from packages.services.checkout import cancel_order
        await cancel_order(db_session, order)

        with pytest.raises(ConflictError, match="Cannot create payment"):
            await create_payment(
                db_session, order, idempotency_key="cancelled-order-key"
            )


class TestProcessPaymentSuccess:
    """Tests for process_payment_success."""

    @pytest.mark.asyncio
    async def test_moves_order_to_paid(self, db_session, sample_product):
        order = await _create_test_order(db_session, sample_product)

        payment = await create_payment(
            db_session, order, idempotency_key="success-key-001"
        )

        # Simulate provider update
        await update_payment_from_provider(
            db_session,
            payment,
            provider_payment_id="yookassa-pay-id-001",
            new_status=PaymentStatus.SUCCEEDED,
            provider_payload={"status": "succeeded"},
        )

        # Process the success
        await process_payment_success(db_session, payment)

        # Reload the order
        refreshed_order = await db_session.get(type(order), order.id)
        assert refreshed_order.status == OrderStatus.PAID, (
            f"order status should be PAID after payment success, got {refreshed_order.status}"
        )

    @pytest.mark.asyncio
    async def test_process_success_idempotent(self, db_session, sample_product):
        """Processing success for an already paid order should not raise."""
        order = await _create_test_order(db_session, sample_product)

        payment = await create_payment(
            db_session, order, idempotency_key="idemp-success-key"
        )

        await update_payment_from_provider(
            db_session,
            payment,
            provider_payment_id="yookassa-pay-id-002",
            new_status=PaymentStatus.SUCCEEDED,
        )

        # Process success twice
        await process_payment_success(db_session, payment)
        await process_payment_success(db_session, payment)

        refreshed_order = await db_session.get(type(order), order.id)
        assert refreshed_order.status == OrderStatus.PAID


class TestUpdatePaymentFromProvider:
    """Tests for update_payment_from_provider."""

    @pytest.mark.asyncio
    async def test_updates_payment_fields(self, db_session, sample_product):
        order = await _create_test_order(db_session, sample_product)

        payment = await create_payment(
            db_session, order, idempotency_key="update-key-001"
        )

        updated = await update_payment_from_provider(
            db_session,
            payment,
            provider_payment_id="yookassa-id-xyz",
            new_status=PaymentStatus.WAITING_CAPTURE,
            confirmation_url="https://yookassa.ru/checkout/confirm/abc",
            provider_payload={"id": "yookassa-id-xyz", "status": "waiting_for_capture"},
        )

        assert updated.provider_payment_id == "yookassa-id-xyz"
        assert updated.status == PaymentStatus.WAITING_CAPTURE
        assert updated.confirmation_url == "https://yookassa.ru/checkout/confirm/abc"
        assert updated.provider_payload["status"] == "waiting_for_capture"
