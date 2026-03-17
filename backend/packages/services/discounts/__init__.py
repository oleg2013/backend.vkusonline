from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.enums import DiscountType
from packages.models.discount import CustomerDiscount, DiscountRule


async def get_active_global_discounts(db: AsyncSession) -> list[DiscountRule]:
    now = datetime.now(UTC)
    stmt = select(DiscountRule).where(
        DiscountRule.is_active.is_(True),
        (DiscountRule.valid_from.is_(None)) | (DiscountRule.valid_from <= now),
        (DiscountRule.valid_until.is_(None)) | (DiscountRule.valid_until > now),
    ).order_by(DiscountRule.priority.desc())
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_customer_discounts(
    db: AsyncSession,
    user_id: str,
) -> list[CustomerDiscount]:
    now = datetime.now(UTC)
    stmt = select(CustomerDiscount).where(
        CustomerDiscount.user_id == user_id,
        CustomerDiscount.is_active.is_(True),
        (CustomerDiscount.valid_from.is_(None)) | (CustomerDiscount.valid_from <= now),
        (CustomerDiscount.valid_until.is_(None)) | (CustomerDiscount.valid_until > now),
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


def calculate_discount(
    subtotal_kopecks: int,
    discounts: list[DiscountRule | CustomerDiscount],
) -> tuple[int, list[dict]]:
    total_discount = 0
    applied = []

    for d in discounts:
        if d.discount_type == DiscountType.PERCENTAGE:
            amount = subtotal_kopecks * d.value // 100
        elif d.discount_type == DiscountType.FIXED_AMOUNT:
            amount = d.value
        else:
            continue

        total_discount += amount
        applied.append({
            "name": d.name,
            "type": d.discount_type,
            "value": d.value,
            "amount": amount,
        })

    # Never go negative
    total_discount = min(total_discount, subtotal_kopecks)
    return total_discount, applied
