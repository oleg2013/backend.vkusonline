from __future__ import annotations

from enum import StrEnum


class OrderType(StrEnum):
    PREPAID = "prepaid"
    CODFLOW = "codflow"


class OrderStatus(StrEnum):
    DRAFT = "draft"
    PENDING_PAYMENT = "pending_payment"
    PAID = "paid"
    PENDING_CONFIRMATION = "pending_confirmation"
    CONFIRMED = "confirmed"
    SHIPPED = "shipped"
    READY_FOR_PICKUP = "ready_for_pickup"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"
    CLIENT_DONT_PICKUP = "client_dont_pickup"
    RETURNED_TO_SUPPLIER = "returned_to_supplier"
    REFUNDED = "refunded"


class PaymentStatus(StrEnum):
    PENDING = "pending"
    WAITING_CAPTURE = "waiting_for_capture"
    SUCCEEDED = "succeeded"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"


class ShipmentStatus(StrEnum):
    CREATED = "created"
    ACCEPTED = "accepted"
    IN_TRANSIT = "in_transit"
    ARRIVED = "arrived"
    READY_FOR_PICKUP = "ready_for_pickup"
    ISSUED = "issued"
    RETURNING = "returning"
    RETURNED = "returned"
    CANCELLED = "cancelled"
    LOST = "lost"


class DeliveryProvider(StrEnum):
    FIVEPOST = "5post"
    MAGNIT = "magnit"


class PaymentProvider(StrEnum):
    YOOKASSA = "yookassa"


class CartOwnerType(StrEnum):
    GUEST = "guest"
    USER = "user"


class DiscountType(StrEnum):
    PERCENTAGE = "percentage"
    FIXED_AMOUNT = "fixed_amount"


class PaymentMethod(StrEnum):
    CARD = "card"
    COD = "cod"


class ParcelSize(StrEnum):
    S = "S"
    M = "M"
    L = "L"
