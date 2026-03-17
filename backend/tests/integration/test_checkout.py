"""Integration tests for the checkout service."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from packages.core.exceptions import ConflictError, NotFoundError
from packages.enums import OrderStatus
from packages.models.idempotency import IdempotencyKey
from packages.services.checkout import (
    calculate_quote,
    cancel_order,
    create_order,
)


class TestCalculateQuote:
    """Tests for calculate_quote."""

    @pytest.mark.asyncio
    async def test_calculate_with_valid_items(self, db_session, sample_product):
        items = [{"sku": sample_product.sku, "quantity": 2}]
        quote = await calculate_quote(
            db_session,
            items=items,
            delivery_price_kopecks=30000,
            discount_amount_kopecks=5000,
        )

        expected_subtotal = sample_product.price * 2
        expected_total = expected_subtotal - 5000 + 30000

        assert quote["subtotal"] == expected_subtotal, (
            f"subtotal should be {expected_subtotal}, got {quote['subtotal']}"
        )
        assert quote["discount_amount"] == 5000
        assert quote["delivery_price"] == 30000
        assert quote["total"] == expected_total, (
            f"total should be {expected_total}, got {quote['total']}"
        )
        assert len(quote["items_detail"]) == 1

    @pytest.mark.asyncio
    async def test_calculate_with_invalid_sku_fails(self, db_session):
        items = [{"sku": "NONEXISTENT-SKU", "quantity": 1}]
        with pytest.raises(NotFoundError, match="Product"):
            await calculate_quote(db_session, items, 0)

    @pytest.mark.asyncio
    async def test_items_detail_contains_correct_info(self, db_session, sample_product):
        items = [{"sku": sample_product.sku, "quantity": 3}]
        quote = await calculate_quote(db_session, items, 0)

        detail = quote["items_detail"][0]
        assert detail["sku"] == sample_product.sku
        assert detail["name"] == sample_product.name
        assert detail["quantity"] == 3
        assert detail["unit_price"] == sample_product.price
        assert detail["total_price"] == sample_product.price * 3
        assert detail["weight_grams"] == sample_product.weight_grams
        assert detail["vat_rate"] == sample_product.vat_rate


class TestCreateOrder:
    """Tests for create_order."""

    @pytest.mark.asyncio
    async def test_create_order_with_correct_totals(self, db_session, sample_product):
        order = await create_order(
            db_session,
            items=[{"sku": sample_product.sku, "quantity": 2}],
            customer_email="order@example.com",
            customer_phone="+79991234567",
            customer_name="Test Customer",
            delivery_provider="5post",
            delivery_city="Moscow",
            delivery_address=None,
            pickup_point_id="pp-001",
            pickup_point_name="Test Point",
            customer_delivery_price=30000,
            carrier_estimated_cost=25000,
            discount_amount=5000,
            user_id=None,
            guest_session_id=None,
        )

        expected_subtotal = sample_product.price * 2
        expected_total = expected_subtotal - 5000 + 30000

        assert order is not None, "create_order should return an order"
        assert order.status == OrderStatus.PENDING_PAYMENT
        assert order.subtotal == expected_subtotal
        assert order.discount_amount == 5000
        assert order.customer_delivery_price == 30000
        assert order.total == expected_total
        assert order.customer_email == "order@example.com"
        assert order.order_number.startswith("VK-")

    @pytest.mark.asyncio
    async def test_create_order_with_idempotency_key_returns_same_on_retry(
        self, db_session, sample_product
    ):
        """When the same idempotency_key is used, the second call returns the
        original order instead of creating a duplicate.

        We mock ``store_idempotency_db`` / ``check_idempotency_db`` because the
        IdempotencyKey model has a ``created_at`` column without a default which
        would fail on SQLite.  The logic under test is the checkout service's
        idempotency branching, not the DB persistence layer itself.
        """
        stored: dict[str, IdempotencyKey] = {}

        async def _mock_check(db, key):
            return stored.get(key)

        async def _mock_store(db, key, resource_type, resource_id, response_code, response_body, ttl_hours=24):
            record = IdempotencyKey.__new__(IdempotencyKey)
            record.key = key
            record.resource_type = resource_type
            record.resource_id = resource_id
            record.response_code = response_code
            record.response_body = response_body
            record.expires_at = datetime.now(UTC)
            stored[key] = record
            return record

        with (
            patch("packages.services.checkout.check_idempotency_db", side_effect=_mock_check),
            patch("packages.services.checkout.store_idempotency_db", side_effect=_mock_store),
        ):
            kwargs = dict(
                items=[{"sku": sample_product.sku, "quantity": 1}],
                customer_email="idemp@example.com",
                customer_phone="+79991234567",
                customer_name="Idemp Customer",
                delivery_provider="5post",
                delivery_city="Moscow",
                delivery_address=None,
                pickup_point_id="pp-002",
                pickup_point_name="Test Point 2",
                customer_delivery_price=20000,
                carrier_estimated_cost=15000,
                idempotency_key="unique-idemp-key-001",
            )

            order1 = await create_order(db_session, **kwargs)
            order2 = await create_order(db_session, **kwargs)

        assert order1.id == order2.id, (
            "same idempotency key should return the same order on retry"
        )
        assert order1.order_number == order2.order_number


class TestCancelOrder:
    """Tests for cancel_order."""

    @pytest.mark.asyncio
    async def test_cancel_pending_payment_order(self, db_session, sample_product):
        order = await create_order(
            db_session,
            items=[{"sku": sample_product.sku, "quantity": 1}],
            customer_email="cancel@example.com",
            customer_phone="+79991234567",
            customer_name="Cancel Customer",
            delivery_provider="5post",
            delivery_city="Moscow",
            delivery_address=None,
            pickup_point_id="pp-003",
            pickup_point_name="Test Point 3",
            customer_delivery_price=20000,
            carrier_estimated_cost=15000,
        )

        assert order.status == OrderStatus.PENDING_PAYMENT

        cancelled = await cancel_order(db_session, order)
        assert cancelled.status == OrderStatus.CANCELLED, (
            "order status should be CANCELLED after cancellation"
        )

    @pytest.mark.asyncio
    async def test_cancel_shipped_order_fails(self, db_session, sample_product):
        from packages.services.checkout import update_order_status

        order = await create_order(
            db_session,
            items=[{"sku": sample_product.sku, "quantity": 1}],
            customer_email="shipped@example.com",
            customer_phone="+79991234567",
            customer_name="Shipped Customer",
            delivery_provider="5post",
            delivery_city="Moscow",
            delivery_address=None,
            pickup_point_id="pp-004",
            pickup_point_name="Test Point 4",
            customer_delivery_price=20000,
            carrier_estimated_cost=15000,
        )

        # Move to a non-cancellable status
        await update_order_status(db_session, order, OrderStatus.SHIPPED)

        with pytest.raises(ConflictError, match="Cannot cancel"):
            await cancel_order(db_session, order)

    @pytest.mark.asyncio
    async def test_cancel_already_cancelled_order_fails(self, db_session, sample_product):
        order = await create_order(
            db_session,
            items=[{"sku": sample_product.sku, "quantity": 1}],
            customer_email="dup-cancel@example.com",
            customer_phone="+79991234567",
            customer_name="Dup Cancel",
            delivery_provider="5post",
            delivery_city="Moscow",
            delivery_address=None,
            pickup_point_id="pp-005",
            pickup_point_name="Test Point 5",
            customer_delivery_price=20000,
            carrier_estimated_cost=15000,
        )

        await cancel_order(db_session, order)

        with pytest.raises(ConflictError, match="Cannot cancel"):
            await cancel_order(db_session, order)
