"""Unit tests for packages.services.discounts."""

from __future__ import annotations

import pytest

from packages.enums import DiscountType
from packages.services.discounts import calculate_discount


class _FakeDiscount:
    """Lightweight stand-in for DiscountRule / CustomerDiscount.

    Only the fields used by calculate_discount are needed:
    discount_type, value, and name.
    """

    def __init__(self, name: str, discount_type: str, value: int) -> None:
        self.name = name
        self.discount_type = discount_type
        self.value = value


class TestCalculateDiscount:
    """Tests for calculate_discount."""

    def test_percentage_discount(self):
        discounts = [_FakeDiscount("10% off", DiscountType.PERCENTAGE, 10)]
        subtotal = 100_000  # 1000.00 RUB in kopecks
        total_discount, applied = calculate_discount(subtotal, discounts)

        assert total_discount == 10_000, (
            f"10% of 100_000 should be 10_000, got {total_discount}"
        )
        assert len(applied) == 1
        assert applied[0]["name"] == "10% off"
        assert applied[0]["amount"] == 10_000

    def test_fixed_amount_discount(self):
        discounts = [_FakeDiscount("500 RUB off", DiscountType.FIXED_AMOUNT, 50_000)]
        subtotal = 200_000  # 2000.00 RUB
        total_discount, applied = calculate_discount(subtotal, discounts)

        assert total_discount == 50_000, (
            f"fixed discount of 50_000 should be 50_000, got {total_discount}"
        )
        assert len(applied) == 1
        assert applied[0]["amount"] == 50_000

    def test_discount_does_not_exceed_subtotal(self):
        discounts = [
            _FakeDiscount("Big discount", DiscountType.FIXED_AMOUNT, 300_000),
        ]
        subtotal = 100_000
        total_discount, applied = calculate_discount(subtotal, discounts)

        assert total_discount == subtotal, (
            "total discount should not exceed the subtotal"
        )

    def test_multiple_discounts_combined(self):
        discounts = [
            _FakeDiscount("10% off", DiscountType.PERCENTAGE, 10),
            _FakeDiscount("200 RUB off", DiscountType.FIXED_AMOUNT, 20_000),
        ]
        subtotal = 100_000
        total_discount, applied = calculate_discount(subtotal, discounts)

        # 10% of 100_000 = 10_000 + 20_000 fixed = 30_000
        assert total_discount == 30_000, (
            f"combined discounts should be 30_000, got {total_discount}"
        )
        assert len(applied) == 2

    def test_empty_discounts_list_returns_zero(self):
        total_discount, applied = calculate_discount(100_000, [])

        assert total_discount == 0, "no discounts should result in 0 discount"
        assert applied == [], "applied list should be empty"

    def test_unknown_discount_type_is_skipped(self):
        discounts = [_FakeDiscount("Mystery", "mystery_type", 10_000)]
        total_discount, applied = calculate_discount(100_000, discounts)

        assert total_discount == 0, "unknown discount type should be skipped"
        assert applied == []

    def test_percentage_discount_integer_division(self):
        """Verify that percentage discount uses integer division (//)."""
        discounts = [_FakeDiscount("33% off", DiscountType.PERCENTAGE, 33)]
        subtotal = 10_000  # 100.00 RUB
        total_discount, applied = calculate_discount(subtotal, discounts)

        # 10_000 * 33 // 100 = 3_300
        assert total_discount == 3_300, (
            f"33% of 10_000 with integer division should be 3_300, got {total_discount}"
        )
