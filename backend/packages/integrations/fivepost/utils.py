"""Utility functions for 5Post integration."""

from __future__ import annotations

import math

from packages.enums import ShipmentStatus
from packages.integrations.fivepost.models import (
    FivePostCellLimits,
    FivePostPickupPoint,
    FivePostRate,
)

# Weight threshold in kilograms above which surcharge applies.
OVERWEIGHT_THRESHOLD_KG: float = 3.0


def validate_cell_limits(
    point: FivePostPickupPoint,
    length_cm: float,
    width_cm: float,
    height_cm: float,
    weight_grams: float,
) -> bool:
    """Check whether a parcel fits within the pickup point cell limits.

    All dimension arguments are in centimetres; weight is in grams.
    Returns ``True`` if the point has no cell limits or if the parcel fits.
    """
    limits: FivePostCellLimits | None = point.cell_limits
    if limits is None:
        return True

    length_mm = length_cm * 10
    width_mm = width_cm * 10
    height_mm = height_cm * 10
    weight_mg = weight_grams * 1000

    if limits.max_length_mm > 0 and length_mm > limits.max_length_mm:
        return False
    if limits.max_width_mm > 0 and width_mm > limits.max_width_mm:
        return False
    if limits.max_height_mm > 0 and height_mm > limits.max_height_mm:
        return False
    if limits.max_weight_mg > 0 and weight_mg > limits.max_weight_mg:
        return False

    return True


def _get_best_rate(point: FivePostPickupPoint) -> FivePostRate | None:
    """Return the cheapest valid rate for a pickup point."""
    valid = [r for r in point.rates if r.rate_value_with_vat > 0]
    if not valid:
        return None
    return min(valid, key=lambda r: r.rate_value_with_vat)


def calculate_delivery_cost(rate: FivePostRate, weight_mg: int) -> float:
    """Calculate delivery cost from a rate and parcel weight.

    Formula:
        base = rate_value_with_vat
        if weight > 3 kg:
            base += rate_extra_value_with_vat * ceil(overweight_kg)

    Args:
        rate: The tariff rate to use.
        weight_mg: Parcel weight in milligrams.

    Returns:
        Delivery cost in roubles.
    """
    weight_kg = weight_mg / 1_000_000
    cost = rate.rate_value_with_vat

    if weight_kg > OVERWEIGHT_THRESHOLD_KG:
        overweight_kg = math.ceil(weight_kg - OVERWEIGHT_THRESHOLD_KG)
        cost += rate.rate_extra_value_with_vat * overweight_kg

    return round(cost, 2)


# Mapping from 5Post status codes to internal ShipmentStatus.
_FIVEPOST_STATUS_MAP: dict[str, ShipmentStatus] = {
    "CREATED": ShipmentStatus.CREATED,
    "NEW": ShipmentStatus.CREATED,
    "ACCEPTED": ShipmentStatus.ACCEPTED,
    "SORTING": ShipmentStatus.IN_TRANSIT,
    "IN_TRANSIT": ShipmentStatus.IN_TRANSIT,
    "DELIVERING": ShipmentStatus.IN_TRANSIT,
    "ON_THE_WAY": ShipmentStatus.IN_TRANSIT,
    "ARRIVED": ShipmentStatus.ARRIVED,
    "READY_FOR_PICKUP": ShipmentStatus.READY_FOR_PICKUP,
    "PLACED_IN_POSTAMAT": ShipmentStatus.READY_FOR_PICKUP,
    "ISSUED": ShipmentStatus.ISSUED,
    "PICKED_UP": ShipmentStatus.ISSUED,
    "DELIVERED": ShipmentStatus.ISSUED,
    "RETURNING": ShipmentStatus.RETURNING,
    "RETURNED": ShipmentStatus.RETURNED,
    "RETURNED_TO_PARTNER": ShipmentStatus.RETURNED,
    "READY_FOR_WITHDRAW_FROM_PICKUP_POINT": ShipmentStatus.RETURNING,
    "WITHDRAWN_FROM_PICKUP_POINT": ShipmentStatus.RETURNING,
    "CANCELLED": ShipmentStatus.CANCELLED,
    "LOST": ShipmentStatus.LOST,
}


def map_fivepost_status(status_code: str) -> ShipmentStatus:
    """Map a 5Post status code string to the internal ``ShipmentStatus`` enum.

    Unknown codes default to ``ShipmentStatus.CREATED``.
    """
    return _FIVEPOST_STATUS_MAP.get(status_code.upper(), ShipmentStatus.CREATED)
