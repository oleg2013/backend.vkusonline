"""Receipt builder for YooKassa 54-FZ integration.

Constructs ``YooKassaReceipt`` objects from application-level order
item data, handling VAT code mapping and amount formatting.
"""

from __future__ import annotations

from packages.integrations.yookassa.models import (
    YooKassaAmount,
    YooKassaReceipt,
    YooKassaReceiptCustomer,
    YooKassaReceiptItem,
)

# VAT rate (percent) -> YooKassa vat_code
# https://yookassa.ru/developers/api#create_payment
_VAT_CODE_MAP: dict[int, int] = {
    0: 1,    # No VAT
    10: 2,   # 10%
    20: 4,   # 20%
    22: 4,   # 22% mapped to code 4 for compatibility
    # Calculated rates (for agents)
    # 10/110 -> 5
    # 20/120 -> 6
}


def vat_rate_to_yookassa_code(vat_rate_percent: int) -> int:
    """Convert a VAT rate percentage to the YooKassa ``vat_code``.

    Mapping:
        0%  -> 1 (no VAT)
        10% -> 2
        20% -> 4
        22% -> 4 (compatibility alias for 20%)

    For calculated rates (10/110, 20/120) use codes 5 and 6 directly.

    Raises ``ValueError`` for unknown rates.
    """
    code = _VAT_CODE_MAP.get(vat_rate_percent)
    if code is None:
        raise ValueError(
            f"Unknown VAT rate: {vat_rate_percent}%. "
            f"Supported rates: {sorted(_VAT_CODE_MAP.keys())}"
        )
    return code


def _format_amount(kopecks: int) -> str:
    """Format an amount from kopecks to a rouble string (e.g. ``'123.45'``)."""
    roubles = kopecks / 100
    return f"{roubles:.2f}"


def build_receipt(
    items: list[dict],
    customer_email: str = "",
    customer_phone: str = "",
    customer_name: str = "",
) -> YooKassaReceipt:
    """Build a ``YooKassaReceipt`` from a list of order item dicts.

    Each dict in ``items`` must contain:
        - ``name`` (str): product name / description
        - ``quantity`` (int | float): number of units
        - ``unit_price_kopecks`` (int): unit price in kopecks
        - ``vat_rate`` (int): VAT rate as a percentage (0, 10, 20, 22)

    Important:
        The ``amount`` in each receipt item is the **unit** price, not the
        total.  YooKassa multiplies by ``quantity`` internally.
    """
    receipt_items: list[YooKassaReceiptItem] = []

    for item in items:
        name: str = item["name"]
        quantity = item["quantity"]
        unit_price_kopecks: int = item["unit_price_kopecks"]
        vat_rate: int = item.get("vat_rate", 0)
        payment_subject: str = item.get("payment_subject", "commodity")

        receipt_items.append(
            YooKassaReceiptItem(
                description=name[:128],  # YooKassa limit
                quantity=str(quantity),
                amount=YooKassaAmount(
                    value=_format_amount(unit_price_kopecks),
                    currency="RUB",
                ),
                vat_code=vat_rate_to_yookassa_code(vat_rate),
                payment_subject=payment_subject,
                payment_mode="full_payment",
            )
        )

    customer = YooKassaReceiptCustomer(
        full_name=customer_name,
        phone=customer_phone,
        email=customer_email,
    )

    return YooKassaReceipt(
        customer=customer,
        items=receipt_items,
        tax_system_code=1,
    )
