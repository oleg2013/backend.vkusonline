"""Utility functions for Magnit Post integration."""

from __future__ import annotations

from packages.enums import ParcelSize, ShipmentStatus

# Maximum dimensions (cm) and weight (grams) for each parcel size.
_SIZE_LIMITS: dict[ParcelSize, tuple[float, float, float, float]] = {
    # (length_cm, width_cm, height_cm, max_weight_g)
    ParcelSize.S: (25, 15, 10, 2000),
    ParcelSize.M: (35, 25, 15, 5000),
    ParcelSize.L: (45, 30, 20, 10000),
}


def determine_parcel_size(
    weight_grams: float,
    length_cm: float,
    width_cm: float,
    height_cm: float,
) -> ParcelSize:
    """Determine the Magnit parcel size category for given dimensions.

    Size limits:
        S: 25x15x10 cm, up to 2 kg
        M: 35x25x15 cm, up to 5 kg
        L: 45x30x20 cm, up to 10 kg

    Dimensions are compared after sorting so that the longest side is
    checked against the longest limit, etc.  If the parcel does not fit
    any size, ``ParcelSize.L`` is returned as the maximum category.
    """
    dims = sorted([length_cm, width_cm, height_cm], reverse=True)

    for size in (ParcelSize.S, ParcelSize.M, ParcelSize.L):
        max_l, max_w, max_h, max_wt = _SIZE_LIMITS[size]
        limits = sorted([max_l, max_w, max_h], reverse=True)
        if (
            dims[0] <= limits[0]
            and dims[1] <= limits[1]
            and dims[2] <= limits[2]
            and weight_grams <= max_wt
        ):
            return size

    return ParcelSize.L


# Mapping from Magnit status strings to internal ShipmentStatus.
_MAGNIT_STATUS_MAP: dict[str, ShipmentStatus] = {
    "NEW": ShipmentStatus.CREATED,
    "CREATING": ShipmentStatus.CREATED,
    "CREATED": ShipmentStatus.CREATED,
    "ACCEPTED": ShipmentStatus.ACCEPTED,
    "DELIVERING": ShipmentStatus.IN_TRANSIT,
    "DELIVERING_STARTED": ShipmentStatus.IN_TRANSIT,
    "IN_TRANSIT": ShipmentStatus.IN_TRANSIT,
    "ARRIVED": ShipmentStatus.ARRIVED,
    "READY_FOR_PICKUP": ShipmentStatus.READY_FOR_PICKUP,
    "ISSUED": ShipmentStatus.ISSUED,
    "DELIVERED": ShipmentStatus.ISSUED,
    "DESTROYED": ShipmentStatus.RETURNED,
    "RETURNED": ShipmentStatus.RETURNED,
    "RETURNING": ShipmentStatus.RETURNING,
    "CANCELLED": ShipmentStatus.CANCELLED,
    "CANCELED": ShipmentStatus.CANCELLED,
}


def map_magnit_status(status_str: str) -> ShipmentStatus:
    """Map a Magnit status string to the internal ``ShipmentStatus`` enum.

    Unknown values default to ``ShipmentStatus.CREATED``.
    """
    return _MAGNIT_STATUS_MAP.get(status_str.upper(), ShipmentStatus.CREATED)
