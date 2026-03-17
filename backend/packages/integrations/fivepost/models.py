"""Pydantic models for 5Post API data."""

from __future__ import annotations

from pydantic import BaseModel, Field


class FivePostRate(BaseModel):
    """Tariff rate for a pickup point."""

    rate_type: str = ""
    rate_value: float = 0.0
    rate_value_with_vat: float = 0.0
    rate_extra_value: float = 0.0
    rate_extra_value_with_vat: float = 0.0
    zone: str = ""
    currency: str = "RUB"
    vat: int = 0


class FivePostCellLimits(BaseModel):
    """Maximum parcel dimensions for a pickup point cell."""

    max_width_mm: int = 0
    max_height_mm: int = 0
    max_length_mm: int = 0
    max_weight_mg: int = 0


class FivePostWorkHours(BaseModel):
    """Working hours for a single day."""

    day: str = ""
    opens_at: str = ""
    closes_at: str = ""


class FivePostPickupPoint(BaseModel):
    """5Post pickup point (postamat / PVZ)."""

    id: str = ""
    name: str = ""
    type: str = ""
    full_address: str = ""
    city: str = ""
    lat: float = 0.0
    lng: float = 0.0
    cash_allowed: bool = False
    card_allowed: bool = False
    rates: list[FivePostRate] = Field(default_factory=list)
    cell_limits: FivePostCellLimits | None = None
    additional: str = ""
    work_hours: list[FivePostWorkHours] = Field(default_factory=list)
    phone: str = ""
    short_address: str = ""
    partner_name: str = ""
    mdm_code: str = ""


class FivePostProduct(BaseModel):
    """Product item inside a 5Post order."""

    name: str
    quantity: int
    price: float
    weight_grams: float
    vat: int = 22
    vendor_code: str = ""


class FivePostCargo(BaseModel):
    """Cargo (parcel) within an order."""

    sender_cargo_id: str
    height_mm: int
    length_mm: int
    width_mm: int
    weight_mg: int
    price: float
    currency: str = "RUB"
    vat: int = 22
    products: list[FivePostProduct] = Field(default_factory=list)


class FivePostOrderCost(BaseModel):
    """Cost parameters for an order."""

    delivery_cost: float = 0.0
    payment_value: float = 0.0
    payment_currency: str = "RUB"
    payment_type: str = "PREPAYMENT"
    price: float = 0.0
    price_currency: str = "RUB"


class FivePostOrder(BaseModel):
    """Order payload for 5Post API v3."""

    sender_order_id: str
    client_order_id: str
    client_name: str
    client_phone: str
    client_email: str
    sender_location: str
    receiver_location: str
    undeliverable_option: str = "RETURN"
    cost: FivePostOrderCost = Field(default_factory=FivePostOrderCost)
    cargoes: list[FivePostCargo] = Field(default_factory=list)

    def to_api_dict(self) -> dict:
        """Convert to the 5Post API v3 request format."""
        cargoes_list = []
        for cargo in self.cargoes:
            product_values = []
            for p in cargo.products:
                pv: dict = {
                    "name": p.name,
                    "value": p.quantity,
                    "price": p.price,
                    "vat": p.vat,
                    "currency": cargo.currency,
                }
                if p.vendor_code:
                    pv["vendorCode"] = p.vendor_code
                product_values.append(pv)

            cargoes_list.append(
                {
                    "senderCargoId": cargo.sender_cargo_id,
                    "height": cargo.height_mm,
                    "length": cargo.length_mm,
                    "width": cargo.width_mm,
                    "weight": cargo.weight_mg,
                    "price": cargo.price,
                    "currency": cargo.currency,
                    "vat": cargo.vat,
                    "productValues": product_values,
                }
            )

        return {
            "partnerOrders": [
                {
                    "senderOrderId": self.sender_order_id,
                    "clientOrderId": self.client_order_id,
                    "clientName": self.client_name,
                    "clientPhone": self.client_phone,
                    "clientEmail": self.client_email,
                    "senderLocation": self.sender_location,
                    "receiverLocation": self.receiver_location,
                    "undeliverableOption": self.undeliverable_option,
                    "cost": {
                        "deliveryCost": self.cost.delivery_cost,
                        "deliveryCostCurrency": self.cost.payment_currency,
                        "paymentValue": self.cost.payment_value,
                        "paymentCurrency": self.cost.payment_currency,
                        "paymentType": self.cost.payment_type,
                        "price": self.cost.price,
                        "priceCurrency": self.cost.price_currency,
                    },
                    "cargoes": cargoes_list,
                }
            ]
        }


class FivePostTrackingEvent(BaseModel):
    """Single tracking event from 5Post status history."""

    status_code: str = ""
    status_name: str = ""
    timestamp: str = ""
    description: str = ""


class FivePostStatus(BaseModel):
    """5Post order status with tracking events."""

    order_id: str = ""
    sender_order_id: str = ""
    status_code: str = ""
    status_name: str = ""
    tracking_events: list[FivePostTrackingEvent] = Field(default_factory=list)
