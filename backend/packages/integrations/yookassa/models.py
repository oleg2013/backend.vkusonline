"""Pydantic models for YooKassa payment API data."""

from __future__ import annotations

from pydantic import BaseModel, Field


class YooKassaAmount(BaseModel):
    """Monetary amount in YooKassa format.

    ``value`` is a string representation of the amount (e.g. ``"100.00"``).
    ``currency`` defaults to ``"RUB"``.
    """

    value: str
    currency: str = "RUB"


class YooKassaReceiptCustomer(BaseModel):
    """Customer information for a YooKassa receipt (54-FZ)."""

    full_name: str = ""
    phone: str = ""
    email: str = ""


class YooKassaReceiptItem(BaseModel):
    """Single line item in a YooKassa receipt.

    Important: ``amount`` is the **unit** price, not the total.
    YooKassa multiplies ``amount`` by ``quantity`` internally.
    """

    description: str
    quantity: str
    amount: YooKassaAmount
    vat_code: int
    payment_subject: str = "commodity"
    payment_mode: str = "full_payment"


class YooKassaReceipt(BaseModel):
    """YooKassa receipt for 54-FZ online cash register integration."""

    customer: YooKassaReceiptCustomer
    items: list[YooKassaReceiptItem] = Field(default_factory=list)
    tax_system_code: int = 1

    def to_api_dict(self) -> dict:
        """Convert to the dict expected by the YooKassa API."""
        customer_dict: dict = {}
        if self.customer.full_name:
            customer_dict["full_name"] = self.customer.full_name
        if self.customer.phone:
            customer_dict["phone"] = self.customer.phone
        if self.customer.email:
            customer_dict["email"] = self.customer.email

        return {
            "customer": customer_dict,
            "items": [
                {
                    "description": item.description,
                    "quantity": item.quantity,
                    "amount": {
                        "value": item.amount.value,
                        "currency": item.amount.currency,
                    },
                    "vat_code": item.vat_code,
                    "payment_subject": item.payment_subject,
                    "payment_mode": item.payment_mode,
                }
                for item in self.items
            ],
            "tax_system_code": self.tax_system_code,
        }


class YooKassaConfirmation(BaseModel):
    """Payment confirmation details returned by YooKassa."""

    type: str = ""
    confirmation_url: str = ""


class YooKassaPayment(BaseModel):
    """YooKassa payment object."""

    id: str = ""
    status: str = ""
    amount: YooKassaAmount | None = None
    confirmation: YooKassaConfirmation | None = None
    description: str = ""
    metadata: dict = Field(default_factory=dict)
    paid: bool = False
    refundable: bool = False
    created_at: str = ""
