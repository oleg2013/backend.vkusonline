"""Pydantic models for Magnit Post API data."""

from __future__ import annotations

from pydantic import BaseModel, Field


class MagnitWorkSchedule(BaseModel):
    """Working schedule entry for a Magnit pickup point.

    Magnit API returns: {"day": "MON", "from": "08:30", "till": "22:30"}
    We normalise to opens_at / closes_at for uniform handling.
    """

    day: str = ""
    opens_at: str = Field("", alias="from")
    closes_at: str = Field("", alias="till")

    model_config = {"populate_by_name": True}


class MagnitCoordinates(BaseModel):
    """Coordinates sub-object in Magnit API response."""

    latitude: float | None = None
    longitude: float | None = None


class MagnitPickupPoint(BaseModel):
    """Magnit Post pickup point (PVZ).

    Maps Magnit API field names to our internal names:
      - workHours -> work_schedule
      - coordinates.latitude/longitude -> lat/lon
    """

    key: str = ""
    name: str = ""
    city: str = ""
    address: str = ""
    lat: float | None = None
    lon: float | None = None
    coordinates: MagnitCoordinates | None = None
    work_schedule: list[MagnitWorkSchedule] = Field(default_factory=list, alias="workHours")
    payment_method: list[str] = Field(default_factory=list)
    region: str = ""
    status: str = ""
    type: str = ""

    model_config = {"populate_by_name": True}

    def model_post_init(self, __context: object) -> None:
        """Extract lat/lon from coordinates if not set directly."""
        if self.coordinates and self.lat is None:
            self.lat = self.coordinates.latitude
        if self.coordinates and self.lon is None:
            self.lon = self.coordinates.longitude


class MagnitReceiver(BaseModel):
    """Recipient information for a Magnit order."""

    phone_number: str
    first_name: str
    family_name: str
    last_name: str = ""


class MagnitParcelCharacteristic(BaseModel):
    """Physical characteristics of a parcel in millimetres and grams."""

    weight: int = 0
    length: int = 0
    width: int = 0
    height: int = 0


# ---------------------------------------------------------------------------
# Payment models (V2 API — COD / prepaid support)
# ---------------------------------------------------------------------------


class MagnitParcelItem(BaseModel):
    """A single goods item inside a parcel (for COD orders).

    All monetary values are in kopecks.
    Magnit V2 API: parcels[].parcel_payment.items[]
    """

    good_id: str = ""
    name: str = ""
    unit: str = "piece"  # "piece" | "weight"
    quantity: int = 1
    unit_price: int = 0          # kopecks
    total_sum_for_item: int = 0  # kopecks
    vat_rate: int = 22           # 0, 5, 7, 10, 20, 22


class MagnitParcelPayment(BaseModel):
    """Payment details for a parcel.

    billing_type controls whether the recipient pays on pickup:
      - "not_paid"     — COD (наложенный платёж), recipient pays at pickup point
      - "already_paid" — prepaid, no payment at pickup point

    When billing_type is "not_paid", items[] and total_sum_for_parcel
    must be provided so Magnit knows how much to collect.
    """

    billing_type: str = "already_paid"  # "not_paid" | "already_paid"
    items: list[MagnitParcelItem] = Field(default_factory=list)
    total_sum_for_parcel: int = 0  # kopecks


class MagnitOrderPayment(BaseModel):
    """Order-level payment details (V2 API).

    Required when parcels contain billing_type="not_paid" (COD).
    All monetary values are in kopecks.
    """

    delivery_cost: int = 0          # delivery cost in kopecks
    total_sum_for_order: int = 0    # total for all parcels in kopecks
    supplier_inn: str = ""
    supplier_name: str = ""
    vat_payer: bool = True


class MagnitParcel(BaseModel):
    """Parcel within a Magnit order."""

    declared_value: int = 0
    characteristic: MagnitParcelCharacteristic = Field(
        default_factory=MagnitParcelCharacteristic,
    )
    parcel_payment: MagnitParcelPayment | None = None
    size: str = ""


class MagnitOrder(BaseModel):
    """Order payload for the Magnit Post V2 API."""

    order_num: str = ""
    warehouse_uuid: str = ""
    customer_order_id: str = ""
    pickup_point: dict = Field(default_factory=dict)
    receiver: MagnitReceiver | None = None
    parcels: list[MagnitParcel] = Field(default_factory=list)
    order_payment: MagnitOrderPayment | None = None
    return_type: str = "return"
    return_warehouse_id: str = ""
    external_order_id: str = ""

    def to_api_dict(self) -> dict:
        """Convert to the Magnit V2 API request format."""
        body: dict = {
            "pickup_point": self.pickup_point,
            "warehouse_id": self.warehouse_uuid,
            "customer_order_id": self.customer_order_id,
            "return_type": self.return_type,
            "return_warehouse_id": self.return_warehouse_id or self.warehouse_uuid,
        }

        if self.receiver:
            body["recipient"] = {
                "phone_number": self.receiver.phone_number,
                "first_name": self.receiver.first_name,
                "family_name": self.receiver.family_name,
            }
            if self.receiver.last_name:
                body["recipient"]["last_name"] = self.receiver.last_name

        if self.parcels:
            parcels_list = []
            for p in self.parcels:
                parcel_dict: dict = {
                    "declared_value": p.declared_value,
                    "characteristic": {
                        "weight": p.characteristic.weight,
                        "length": p.characteristic.length,
                        "width": p.characteristic.width,
                        "height": p.characteristic.height,
                    },
                }
                if p.parcel_payment:
                    pp = p.parcel_payment
                    payment_dict: dict = {
                        "billing_type": pp.billing_type,
                    }
                    if pp.items:
                        payment_dict["items"] = [
                            {
                                "good_id": item.good_id,
                                "name": item.name,
                                "unit": item.unit,
                                "quantity": item.quantity,
                                "unit_price": item.unit_price,
                                "total_sum_for_item": item.total_sum_for_item,
                                "vat_rate": item.vat_rate,
                            }
                            for item in pp.items
                        ]
                    if pp.total_sum_for_parcel:
                        payment_dict["total_sum_for_parcel"] = pp.total_sum_for_parcel
                    parcel_dict["parcel_payment"] = payment_dict
                parcels_list.append(parcel_dict)
            body["parcels"] = parcels_list

        if self.order_payment:
            op = self.order_payment
            body["order_payment"] = {
                "delivery_cost": op.delivery_cost,
                "total_sum_for_order": op.total_sum_for_order,
            }
            if op.supplier_inn:
                body["order_payment"]["supplier_inn"] = op.supplier_inn
            if op.supplier_name:
                body["order_payment"]["supplier_name"] = op.supplier_name
            body["order_payment"]["vat_payer"] = op.vat_payer

        if self.external_order_id:
            body["external_order_id"] = self.external_order_id

        return body


class MagnitEstimate(BaseModel):
    """Delivery estimate returned by the Magnit estimate endpoint."""

    delivery_cost: float = 0.0
    delivery_days_min: int = 0
    delivery_days_max: int = 0
    pickup_point_key: str = ""
