"""Unit tests for packages.integrations.yookassa.receipt_builder."""

from __future__ import annotations

import pytest

from packages.integrations.yookassa.receipt_builder import (
    build_receipt,
    vat_rate_to_yookassa_code,
)


class TestVatRateToYookassaCode:
    """Tests for vat_rate_to_yookassa_code."""

    def test_zero_percent(self):
        assert vat_rate_to_yookassa_code(0) == 1, "0% VAT should map to code 1"

    def test_ten_percent(self):
        assert vat_rate_to_yookassa_code(10) == 2, "10% VAT should map to code 2"

    def test_twenty_percent(self):
        assert vat_rate_to_yookassa_code(20) == 4, "20% VAT should map to code 4"

    def test_twenty_two_percent(self):
        assert vat_rate_to_yookassa_code(22) == 4, "22% VAT should map to code 4 (compatibility)"

    def test_unknown_rate_raises_value_error(self):
        with pytest.raises(ValueError, match="Unknown VAT rate"):
            vat_rate_to_yookassa_code(15)


class TestBuildReceipt:
    """Tests for build_receipt."""

    def _sample_items(self) -> list[dict]:
        return [
            {
                "name": "Earl Grey Premium 100g",
                "quantity": 2,
                "unit_price_kopecks": 45000,
                "vat_rate": 20,
            },
            {
                "name": "Jasmine Green 50g",
                "quantity": 1,
                "unit_price_kopecks": 32000,
                "vat_rate": 10,
            },
        ]

    def test_receipt_has_correct_number_of_items(self):
        receipt = build_receipt(self._sample_items())
        assert len(receipt.items) == 2, "receipt should contain 2 items"

    def test_receipt_item_amount_is_unit_price_not_total(self):
        """The amount in each receipt item must be the unit price, not quantity * unit price."""
        receipt = build_receipt(self._sample_items())
        first_item = receipt.items[0]
        # unit_price_kopecks=45000 -> "450.00"
        assert first_item.amount.value == "450.00", (
            f"item amount should be unit price '450.00', got '{first_item.amount.value}'"
        )

    def test_receipt_item_quantity_is_string(self):
        receipt = build_receipt(self._sample_items())
        for item in receipt.items:
            assert isinstance(item.quantity, str), (
                f"quantity should be a string, got {type(item.quantity)}"
            )

    def test_receipt_item_quantity_values(self):
        receipt = build_receipt(self._sample_items())
        assert receipt.items[0].quantity == "2", "first item quantity should be '2'"
        assert receipt.items[1].quantity == "1", "second item quantity should be '1'"

    def test_receipt_currency_is_rub(self):
        receipt = build_receipt(self._sample_items())
        for item in receipt.items:
            assert item.amount.currency == "RUB", "currency should be RUB"

    def test_receipt_vat_codes(self):
        receipt = build_receipt(self._sample_items())
        assert receipt.items[0].vat_code == 4, "20% VAT should produce code 4"
        assert receipt.items[1].vat_code == 2, "10% VAT should produce code 2"

    def test_receipt_customer_info(self):
        receipt = build_receipt(
            self._sample_items(),
            customer_email="test@example.com",
            customer_phone="+79991234567",
            customer_name="Test User",
        )
        assert receipt.customer.email == "test@example.com"
        assert receipt.customer.phone == "+79991234567"
        assert receipt.customer.full_name == "Test User"

    def test_receipt_tax_system_code(self):
        receipt = build_receipt(self._sample_items())
        assert receipt.tax_system_code == 1, "tax_system_code should be 1 (USN)"

    def test_receipt_item_description_truncated_at_128(self):
        items = [
            {
                "name": "A" * 200,
                "quantity": 1,
                "unit_price_kopecks": 10000,
                "vat_rate": 0,
            },
        ]
        receipt = build_receipt(items)
        assert len(receipt.items[0].description) == 128, (
            "description should be truncated to 128 characters"
        )

    def test_receipt_item_payment_subject_and_mode(self):
        receipt = build_receipt(self._sample_items())
        for item in receipt.items:
            assert item.payment_subject == "commodity"
            assert item.payment_mode == "full_payment"

    def test_receipt_structure_via_to_api_dict(self):
        receipt = build_receipt(
            self._sample_items(),
            customer_email="test@example.com",
        )
        api_dict = receipt.to_api_dict()
        assert "customer" in api_dict
        assert "items" in api_dict
        assert "tax_system_code" in api_dict
        assert api_dict["customer"]["email"] == "test@example.com"
        assert len(api_dict["items"]) == 2
