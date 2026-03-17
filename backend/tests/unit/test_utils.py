"""Unit tests for packages.core.utils."""

from __future__ import annotations

import re

import pytest

from packages.core.utils import (
    generate_order_number,
    haversine_distance,
    validate_email,
    validate_phone,
)


class TestHaversineDistance:
    """Tests for haversine_distance."""

    def test_moscow_to_saint_petersburg(self):
        """Moscow (55.7558, 37.6173) to St Petersburg (59.9343, 30.3351) is approx 634 km."""
        dist = haversine_distance(55.7558, 37.6173, 59.9343, 30.3351)
        assert 620 < dist < 650, (
            f"Moscow to St Petersburg should be ~634 km, got {dist:.1f} km"
        )

    def test_same_point_returns_zero(self):
        dist = haversine_distance(55.7558, 37.6173, 55.7558, 37.6173)
        assert dist == pytest.approx(0.0, abs=0.001), (
            "Distance from a point to itself should be zero"
        )

    def test_known_short_distance(self):
        """Moscow Kremlin to Red Square (roughly 0.5 km)."""
        dist = haversine_distance(55.7520, 37.6175, 55.7539, 37.6208)
        assert 0.1 < dist < 1.0, (
            f"Kremlin to Red Square should be a short distance, got {dist:.3f} km"
        )

    def test_symmetry(self):
        d1 = haversine_distance(55.7558, 37.6173, 59.9343, 30.3351)
        d2 = haversine_distance(59.9343, 30.3351, 55.7558, 37.6173)
        assert d1 == pytest.approx(d2, rel=1e-10), (
            "haversine_distance should be symmetric"
        )


class TestValidatePhone:
    """Tests for validate_phone."""

    def test_valid_plus_seven_format(self):
        result = validate_phone("+79991234567")
        assert result == "+79991234567", "valid +7 format should pass through"

    def test_valid_eight_format(self):
        result = validate_phone("89991234567")
        assert result == "+79991234567", "8-prefix should be converted to +7"

    def test_valid_seven_format(self):
        result = validate_phone("79991234567")
        assert result == "+79991234567", "7-prefix (without +) should be converted to +7"

    def test_valid_nine_format(self):
        result = validate_phone("9991234567")
        assert result == "+79991234567", "9-prefix (10 digits) should be converted to +7"

    def test_phone_with_spaces_and_dashes(self):
        result = validate_phone("+7 (999) 123-45-67")
        assert result == "+79991234567", "phone with formatting characters should be cleaned"

    def test_invalid_phone_too_short(self):
        result = validate_phone("+7999")
        assert result is None, "too-short phone number should return None"

    def test_invalid_phone_too_long(self):
        result = validate_phone("+799912345678888")
        assert result is None, "too-long phone number should return None"

    def test_invalid_phone_non_russian(self):
        result = validate_phone("+14155551234")
        assert result is None, "non-Russian phone number should return None"

    def test_empty_phone(self):
        result = validate_phone("")
        assert result is None, "empty string should return None"


class TestValidateEmail:
    """Tests for validate_email."""

    def test_valid_email(self):
        assert validate_email("user@example.com") is True

    def test_valid_email_with_subdomain(self):
        assert validate_email("user@mail.example.com") is True

    def test_valid_email_with_plus(self):
        assert validate_email("user+tag@example.com") is True

    def test_invalid_email_no_at(self):
        assert validate_email("userexample.com") is False

    def test_invalid_email_no_domain(self):
        assert validate_email("user@") is False

    def test_invalid_email_no_tld(self):
        assert validate_email("user@example") is False

    def test_invalid_email_with_spaces(self):
        assert validate_email("user @example.com") is False

    def test_invalid_email_empty_string(self):
        assert validate_email("") is False


class TestGenerateOrderNumber:
    """Tests for generate_order_number."""

    def test_format_matches_pattern(self):
        order_num = generate_order_number()
        pattern = r"^VK-\d{6}-[A-Z0-9]{6}$"
        assert re.match(pattern, order_num), (
            f"Order number '{order_num}' does not match VK-YYMMDD-XXXXXX format"
        )

    def test_starts_with_vk_prefix(self):
        order_num = generate_order_number()
        assert order_num.startswith("VK-"), "order number should start with 'VK-'"

    def test_uniqueness(self):
        numbers = {generate_order_number() for _ in range(100)}
        assert len(numbers) == 100, "100 generated order numbers should all be unique"

    def test_contains_date_part(self):
        from datetime import UTC, datetime

        order_num = generate_order_number()
        date_part = order_num.split("-")[1]
        # Should be parseable as YYMMDD
        today = datetime.now(UTC)
        expected_prefix = today.strftime("%y%m%d")
        assert date_part == expected_prefix, (
            f"date part '{date_part}' should match today's date '{expected_prefix}'"
        )
