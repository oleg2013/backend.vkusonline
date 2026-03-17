"""Unit tests for 5Post and Magnit delivery utility functions."""

from __future__ import annotations

import pytest

from packages.enums import ParcelSize, ShipmentStatus
from packages.integrations.fivepost.models import (
    FivePostCellLimits,
    FivePostPickupPoint,
    FivePostRate,
)
from packages.integrations.fivepost.utils import (
    calculate_delivery_cost,
    map_fivepost_status,
    validate_cell_limits,
)
from packages.integrations.magnit.utils import (
    determine_parcel_size,
    map_magnit_status,
)


# =====================================================================
# 5Post utils
# =====================================================================


class TestValidateCellLimits:
    """Tests for validate_cell_limits."""

    def _make_point(self, cell_limits: FivePostCellLimits | None) -> FivePostPickupPoint:
        return FivePostPickupPoint(
            id="test-point",
            name="Test Point",
            cell_limits=cell_limits,
        )

    def test_parcel_fits_within_limits(self):
        limits = FivePostCellLimits(
            max_length_mm=600,
            max_width_mm=400,
            max_height_mm=300,
            max_weight_mg=5_000_000,
        )
        point = self._make_point(limits)
        # 50cm x 30cm x 20cm, 3000g (all fit)
        assert validate_cell_limits(point, 50, 30, 20, 3000) is True, (
            "parcel within all limits should return True"
        )

    def test_parcel_exceeds_length(self):
        limits = FivePostCellLimits(
            max_length_mm=600,
            max_width_mm=400,
            max_height_mm=300,
            max_weight_mg=5_000_000,
        )
        point = self._make_point(limits)
        # 70cm length = 700mm > 600mm limit
        assert validate_cell_limits(point, 70, 30, 20, 3000) is False, (
            "parcel exceeding length limit should return False"
        )

    def test_parcel_exceeds_weight(self):
        limits = FivePostCellLimits(
            max_length_mm=600,
            max_width_mm=400,
            max_height_mm=300,
            max_weight_mg=5_000_000,
        )
        point = self._make_point(limits)
        # 6000g = 6,000,000 mg > 5,000,000 mg limit
        assert validate_cell_limits(point, 50, 30, 20, 6000) is False, (
            "parcel exceeding weight limit should return False"
        )

    def test_no_cell_limits_always_fits(self):
        point = self._make_point(cell_limits=None)
        assert validate_cell_limits(point, 100, 100, 100, 50000) is True, (
            "point with no cell limits should always accept parcels"
        )

    def test_parcel_at_exact_limit(self):
        limits = FivePostCellLimits(
            max_length_mm=600,
            max_width_mm=400,
            max_height_mm=300,
            max_weight_mg=5_000_000,
        )
        point = self._make_point(limits)
        # Exactly at limits: 60cm x 40cm x 30cm, 5000g
        assert validate_cell_limits(point, 60, 40, 30, 5000) is True, (
            "parcel at exact limits should return True"
        )


class TestCalculateDeliveryCost:
    """Tests for calculate_delivery_cost."""

    def test_base_rate_under_threshold(self):
        rate = FivePostRate(
            rate_value_with_vat=200.0,
            rate_extra_value_with_vat=50.0,
        )
        # 2 kg = 2,000,000 mg (under 3 kg threshold)
        cost = calculate_delivery_cost(rate, 2_000_000)
        assert cost == 200.0, "cost should equal base rate when under weight threshold"

    def test_overweight_surcharge(self):
        rate = FivePostRate(
            rate_value_with_vat=200.0,
            rate_extra_value_with_vat=50.0,
        )
        # 5 kg = 5,000,000 mg => overweight by 2 kg => ceil(2) = 2 extra units
        cost = calculate_delivery_cost(rate, 5_000_000)
        expected = 200.0 + 50.0 * 2  # 300.0
        assert cost == expected, (
            f"cost should include overweight surcharge, expected {expected}, got {cost}"
        )

    def test_overweight_fractional_ceil(self):
        rate = FivePostRate(
            rate_value_with_vat=150.0,
            rate_extra_value_with_vat=30.0,
        )
        # 3.5 kg = 3,500,000 mg => overweight by 0.5 kg => ceil(0.5) = 1
        cost = calculate_delivery_cost(rate, 3_500_000)
        expected = 150.0 + 30.0 * 1  # 180.0
        assert cost == expected, (
            f"fractional overweight should be ceiled up, expected {expected}, got {cost}"
        )

    def test_exactly_at_threshold(self):
        rate = FivePostRate(
            rate_value_with_vat=200.0,
            rate_extra_value_with_vat=50.0,
        )
        # Exactly 3 kg = 3,000,000 mg (at threshold, no surcharge)
        cost = calculate_delivery_cost(rate, 3_000_000)
        assert cost == 200.0, "cost at exactly threshold weight should have no surcharge"


class TestMapFivepostStatus:
    """Tests for map_fivepost_status."""

    @pytest.mark.parametrize(
        ("code", "expected"),
        [
            ("CREATED", ShipmentStatus.CREATED),
            ("NEW", ShipmentStatus.CREATED),
            ("ACCEPTED", ShipmentStatus.ACCEPTED),
            ("SORTING", ShipmentStatus.IN_TRANSIT),
            ("IN_TRANSIT", ShipmentStatus.IN_TRANSIT),
            ("DELIVERING", ShipmentStatus.IN_TRANSIT),
            ("ON_THE_WAY", ShipmentStatus.IN_TRANSIT),
            ("ARRIVED", ShipmentStatus.ARRIVED),
            ("READY_FOR_PICKUP", ShipmentStatus.READY_FOR_PICKUP),
            ("ISSUED", ShipmentStatus.ISSUED),
            ("DELIVERED", ShipmentStatus.ISSUED),
            ("RETURNING", ShipmentStatus.RETURNING),
            ("RETURNED", ShipmentStatus.RETURNED),
            ("CANCELLED", ShipmentStatus.CANCELLED),
            ("LOST", ShipmentStatus.LOST),
        ],
    )
    def test_known_status_codes(self, code: str, expected: ShipmentStatus):
        assert map_fivepost_status(code) == expected, (
            f"5Post status '{code}' should map to {expected}"
        )

    def test_unknown_status_defaults_to_created(self):
        assert map_fivepost_status("UNKNOWN_STATUS") == ShipmentStatus.CREATED, (
            "unknown status code should default to CREATED"
        )

    def test_case_insensitive(self):
        assert map_fivepost_status("created") == ShipmentStatus.CREATED, (
            "status mapping should be case-insensitive"
        )


# =====================================================================
# Magnit utils
# =====================================================================


class TestDetermineParcelSize:
    """Tests for determine_parcel_size."""

    def test_small_parcel(self):
        # 20x10x8 cm, 1500g -> fits S (25x15x10 cm, 2000g)
        size = determine_parcel_size(1500, 20, 10, 8)
        assert size == ParcelSize.S, "small parcel should be categorized as S"

    def test_medium_parcel(self):
        # 30x20x12 cm, 3000g -> too big for S, fits M (35x25x15 cm, 5000g)
        size = determine_parcel_size(3000, 30, 20, 12)
        assert size == ParcelSize.M, "medium parcel should be categorized as M"

    def test_large_parcel(self):
        # 40x28x18 cm, 8000g -> too big for M, fits L (45x30x20 cm, 10000g)
        size = determine_parcel_size(8000, 40, 28, 18)
        assert size == ParcelSize.L, "large parcel should be categorized as L"

    def test_exceeds_large_defaults_to_l(self):
        # 50x35x25 cm, 12000g -> exceeds L -> still returns L
        size = determine_parcel_size(12000, 50, 35, 25)
        assert size == ParcelSize.L, (
            "parcel exceeding all sizes should default to L"
        )

    def test_weight_determines_size(self):
        # Dimensions fit S (20x10x8 cm) but weight (3000g) exceeds S limit (2000g)
        size = determine_parcel_size(3000, 20, 10, 8)
        assert size == ParcelSize.M, (
            "weight exceeding S limit should bump the parcel to M"
        )

    def test_dimension_sorting(self):
        # Provide dimensions in a non-sorted order: width > length
        # 30x10x20 should be compared as 30x20x10 -> fits M
        size = determine_parcel_size(1500, 10, 30, 20)
        assert size == ParcelSize.M, (
            "dimensions should be sorted before comparing to limits"
        )


class TestMapMagnitStatus:
    """Tests for map_magnit_status."""

    @pytest.mark.parametrize(
        ("status", "expected"),
        [
            ("NEW", ShipmentStatus.CREATED),
            ("CREATING", ShipmentStatus.CREATED),
            ("CREATED", ShipmentStatus.CREATED),
            ("ACCEPTED", ShipmentStatus.ACCEPTED),
            ("DELIVERING", ShipmentStatus.IN_TRANSIT),
            ("DELIVERING_STARTED", ShipmentStatus.IN_TRANSIT),
            ("IN_TRANSIT", ShipmentStatus.IN_TRANSIT),
            ("ARRIVED", ShipmentStatus.ARRIVED),
            ("READY_FOR_PICKUP", ShipmentStatus.READY_FOR_PICKUP),
            ("ISSUED", ShipmentStatus.ISSUED),
            ("DELIVERED", ShipmentStatus.ISSUED),
            ("DESTROYED", ShipmentStatus.RETURNED),
            ("RETURNED", ShipmentStatus.RETURNED),
            ("RETURNING", ShipmentStatus.RETURNING),
            ("CANCELLED", ShipmentStatus.CANCELLED),
            ("CANCELED", ShipmentStatus.CANCELLED),
        ],
    )
    def test_known_statuses(self, status: str, expected: ShipmentStatus):
        assert map_magnit_status(status) == expected, (
            f"Magnit status '{status}' should map to {expected}"
        )

    def test_unknown_status_defaults_to_created(self):
        assert map_magnit_status("SOMETHING_NEW") == ShipmentStatus.CREATED, (
            "unknown Magnit status should default to CREATED"
        )

    def test_case_insensitive(self):
        assert map_magnit_status("accepted") == ShipmentStatus.ACCEPTED, (
            "Magnit status mapping should be case-insensitive"
        )
