"""Shipment creation service.

Builds provider-specific orders (Magnit / 5Post), calls provider APIs,
and creates ``Shipment`` records in the database.

For Magnit COD (codflow) orders the service populates ``parcel_payment``
with billing_type ``not_paid``, item details, and ``order_payment`` with
supplier information.  Prepaid orders use ``already_paid``.
"""

from __future__ import annotations

from datetime import UTC, datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from packages.core.config import settings
from packages.core.exceptions import ProviderError
from packages.enums import DeliveryProvider, OrderType, ShipmentStatus
from packages.integrations.fivepost.client import get_client as get_fivepost_client
from packages.integrations.fivepost.models import (
    FivePostCargo,
    FivePostOrder,
    FivePostOrderCost,
    FivePostProduct,
)
from packages.integrations.magnit.client import get_client as get_magnit_client
from packages.integrations.magnit.models import (
    MagnitOrder,
    MagnitOrderPayment,
    MagnitParcel,
    MagnitParcelCharacteristic,
    MagnitParcelItem,
    MagnitParcelPayment,
    MagnitReceiver,
)
from packages.integrations.magnit.utils import determine_parcel_size
from packages.models.base import generate_uuid
from packages.models.order import Order
from packages.models.shipment import Shipment, ShipmentStatusHistory

logger = structlog.get_logger("services.shipments")

# Default parcel dimensions (mm) per size category — used when actual
# per-product dimensions are unavailable.
_DEFAULT_DIMENSIONS: dict[str, tuple[int, int, int]] = {
    "S": (250, 150, 100),
    "M": (350, 250, 150),
    "L": (450, 300, 200),
}


def _total_weight_grams(order: Order) -> int:
    """Sum weight_grams across all order items."""
    return sum(item.weight_grams * item.quantity for item in order.items)


def _parcel_size_and_dims(weight_grams: int) -> tuple[str, tuple[int, int, int]]:
    """Pick parcel size from weight and return (size, (l, w, h) in mm)."""
    size = determine_parcel_size(
        weight_grams, length_cm=25, width_cm=15, height_cm=10
    )
    return size.value, _DEFAULT_DIMENSIONS.get(size.value, _DEFAULT_DIMENSIONS["M"])


def _split_customer_name(full_name: str) -> tuple[str, str, str]:
    """Split 'Фамилия Имя Отчество' into (first, family, last)."""
    parts = full_name.strip().split()
    if len(parts) >= 3:
        return parts[1], parts[0], parts[2]
    if len(parts) == 2:
        return parts[1], parts[0], ""
    return full_name, "", ""


# ---------------------------------------------------------------------------
# Magnit order builder
# ---------------------------------------------------------------------------


def build_magnit_order(order: Order) -> MagnitOrder:
    """Build a ``MagnitOrder`` from an internal ``Order``.

    - CODFLOW → billing_type ``not_paid`` with item list + order_payment
    - PREPAID → billing_type ``already_paid``
    """
    weight = _total_weight_grams(order)
    size, (length, width, height) = _parcel_size_and_dims(weight)

    # Use recipient data if provided (gift order), otherwise customer data
    recv_name = order.recipient_name or order.customer_name
    recv_phone = order.recipient_phone or order.customer_phone

    first_name, family_name, last_name = _split_customer_name(recv_name)

    receiver = MagnitReceiver(
        phone_number=recv_phone,
        first_name=first_name,
        family_name=family_name,
        last_name=last_name,
    )

    characteristic = MagnitParcelCharacteristic(
        weight=weight,
        length=length,
        width=width,
        height=height,
    )

    # COD (codflow) → not_paid with items
    parcel_payment: MagnitParcelPayment | None = None
    order_payment: MagnitOrderPayment | None = None

    if order.order_type == OrderType.CODFLOW:
        items: list[MagnitParcelItem] = []
        for oi in order.items:
            items.append(
                MagnitParcelItem(
                    good_id=oi.product_sku,
                    name=oi.product_name,
                    unit="piece",
                    quantity=oi.quantity,
                    unit_price=oi.unit_price,          # kopecks
                    total_sum_for_item=oi.total_price,  # kopecks
                    vat_rate=oi.vat_rate,
                )
            )

        # total_sum_for_parcel = subtotal - discount (goods only, without delivery)
        goods_total = order.subtotal - order.discount_amount
        parcel_payment = MagnitParcelPayment(
            billing_type="not_paid",
            items=items,
            total_sum_for_parcel=goods_total,
        )

        order_payment = MagnitOrderPayment(
            delivery_cost=order.customer_delivery_price,  # kopecks
            total_sum_for_order=order.total,               # kopecks
            supplier_inn=settings.magnit_supplier_inn,
            supplier_name=settings.magnit_supplier_name,
            vat_payer=settings.magnit_vat_payer,
        )
    else:
        # PREPAID — already_paid, no items needed
        parcel_payment = MagnitParcelPayment(billing_type="already_paid")

    parcel = MagnitParcel(
        declared_value=order.total,
        characteristic=characteristic,
        parcel_payment=parcel_payment,
        size=size,
    )

    magnit_order = MagnitOrder(
        order_num=order.order_number,
        warehouse_uuid=settings.magnit_warehouse_uuid,
        customer_order_id=order.order_number,
        pickup_point={"key": order.pickup_point_id},
        receiver=receiver,
        parcels=[parcel],
        order_payment=order_payment,
        return_type="return",
        return_warehouse_id=settings.magnit_warehouse_uuid,
        external_order_id=order.order_number,
    )

    return magnit_order


# ---------------------------------------------------------------------------
# 5Post order builder
# ---------------------------------------------------------------------------


def build_fivepost_order(order: Order) -> FivePostOrder:
    """Build a ``FivePostOrder`` from an internal ``Order``.

    5Post does not support COD — all orders are sent as PREPAYMENT.
    """
    products: list[FivePostProduct] = []
    for oi in order.items:
        products.append(
            FivePostProduct(
                name=oi.product_name,
                quantity=oi.quantity,
                price=oi.unit_price / 100,  # 5Post expects rubles
                weight_grams=oi.weight_grams,
                vat=oi.vat_rate,
                vendor_code=oi.product_sku,
            )
        )

    weight = _total_weight_grams(order)
    size, (length, width, height) = _parcel_size_and_dims(weight)

    cargo = FivePostCargo(
        sender_cargo_id=f"{order.order_number}-1",
        height_mm=height,
        length_mm=length,
        width_mm=width,
        weight_mg=weight * 1000,  # grams → milligrams
        price=order.total / 100,  # kopecks → rubles
        products=products,
    )

    # 5Post validates: sum(product.price * qty) + deliveryCost == paymentValue
    # When there are order-level discounts (e.g. card payment discount),
    # order.total < sum(products) + delivery, so we must calculate
    # payment_value from actual product prices to pass validation.
    products_total_rub = sum(p.price * p.quantity for p in products)
    delivery_cost_rub = order.customer_delivery_price / 100

    cost = FivePostOrderCost(
        delivery_cost=delivery_cost_rub,
        payment_value=products_total_rub + delivery_cost_rub,
        payment_type="PREPAYMENT",
        price=order.total / 100,  # declared value (actual total paid)
    )

    # Use recipient data if provided (gift order), otherwise customer data
    recv_name = order.recipient_name or order.customer_name
    recv_phone = order.recipient_phone or order.customer_phone

    fivepost_order = FivePostOrder(
        sender_order_id=order.order_number,
        client_order_id=order.order_number,
        client_name=recv_name,
        client_phone=recv_phone,
        client_email=order.customer_email,
        sender_location=settings.fivepost_partner_location_id or settings.fivepost_warehouse_id,
        receiver_location=order.pickup_point_id or "",
        cost=cost,
        cargoes=[cargo],
    )

    return fivepost_order


# ---------------------------------------------------------------------------
# Shipment creation orchestrator
# ---------------------------------------------------------------------------


async def create_shipment(db: AsyncSession, order: Order) -> Shipment:
    """Create a shipment at the delivery provider and save a Shipment record.

    Raises ``ProviderError`` on API failure, ``ValueError`` for unknown provider.
    """
    provider = order.delivery_provider
    weight = _total_weight_grams(order)
    size, _ = _parcel_size_and_dims(weight)

    provider_shipment_id: str | None = None
    provider_order_number: str | None = None
    provider_payload: dict | None = None

    if provider == DeliveryProvider.MAGNIT:
        magnit_order = build_magnit_order(order)
        client = get_magnit_client()
        result = await client.create_order(magnit_order)

        # Magnit V2 response: tracking_number is the primary ID,
        # parcels[].id is the parcel UUID.
        provider_shipment_id = (
            result.get("tracking_number")
            or result.get("id")
            or result.get("order_id")
            or ""
        )
        if not provider_shipment_id and result.get("parcels"):
            provider_shipment_id = result["parcels"][0].get("id", "")
        provider_order_number = result.get("customer_order_id", result.get("order_num", ""))
        provider_payload = result

        if not provider_shipment_id:
            raise ProviderError(
                "magnit",
                "Magnit API did not return an order ID",
                details={"response": result},
            )

        logger.info(
            "shipment_created_magnit",
            order_number=order.order_number,
            provider_id=provider_shipment_id,
            billing_type="not_paid" if order.order_type == OrderType.CODFLOW else "already_paid",
        )

    elif provider == DeliveryProvider.FIVEPOST:
        fivepost_order = build_fivepost_order(order)
        client = get_fivepost_client()
        result = await client.create_order(fivepost_order)

        # 5Post returns {"created": true/false, "orderId": "...", "errors": [...]}
        if not result.get("created", False):
            errors = result.get("errors", [])
            error_msgs = "; ".join(e.get("message", e.get("text", str(e))) for e in errors)
            raise ProviderError(
                "5post",
                f"5Post rejected the order: {error_msgs}",
                details={"response": result},
            )

        provider_shipment_id = result.get("orderId", "")
        provider_order_number = result.get("senderOrderId", order.order_number)
        provider_payload = result

        logger.info(
            "shipment_created_fivepost",
            order_number=order.order_number,
            provider_id=provider_shipment_id,
        )

    else:
        raise ValueError(f"Unknown delivery provider: {provider}")

    # Persist Shipment record
    shipment_id = generate_uuid()
    shipment = Shipment(
        id=shipment_id,
        order_id=order.id,
        provider=provider,
        provider_shipment_id=provider_shipment_id,
        provider_order_number=provider_order_number,
        status=ShipmentStatus.CREATED,
        pickup_point_id=order.pickup_point_id,
        pickup_point_name=order.pickup_point_name,
        weight_grams=weight,
        parcel_size=size,
        provider_payload=provider_payload,
    )
    db.add(shipment)

    # Initial status history entry
    history = ShipmentStatusHistory(
        shipment_id=shipment.id,
        status=ShipmentStatus.CREATED,
        provider_status="CREATED",
        occurred_at=datetime.now(UTC),
    )
    db.add(history)

    await db.flush()

    logger.info(
        "shipment_record_saved",
        shipment_id=shipment.id,
        order_number=order.order_number,
        provider=provider,
    )

    return shipment
