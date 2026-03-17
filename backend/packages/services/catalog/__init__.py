from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from packages.models.catalog import Product, ProductFamily


async def get_families(db: AsyncSession, active_only: bool = True) -> list[ProductFamily]:
    stmt = select(ProductFamily).options(selectinload(ProductFamily.products))
    if active_only:
        stmt = stmt.where(ProductFamily.is_active.is_(True))
    stmt = stmt.order_by(ProductFamily.name)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_products(
    db: AsyncSession,
    category: str | None = None,
    family_slug: str | None = None,
    active_only: bool = True,
) -> list[Product]:
    stmt = select(Product).outerjoin(ProductFamily)
    if active_only:
        stmt = stmt.where(Product.is_active.is_(True))
    if category:
        stmt = stmt.where(ProductFamily.category == category)
    if family_slug:
        stmt = stmt.where(ProductFamily.slug == family_slug)
    stmt = stmt.order_by(Product.sort_order, Product.name)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_product_by_sku(db: AsyncSession, sku: str) -> Product | None:
    stmt = select(Product).where(Product.sku == sku)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()
