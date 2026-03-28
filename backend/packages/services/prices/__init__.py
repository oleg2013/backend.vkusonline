from __future__ import annotations

from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.integrations.price_ftp.parser import ParsedGoodPrice
from packages.models.catalog import Product
from packages.models.price import PriceImportLog, PriceImportSession, PriceType, ProductPrice

logger = structlog.get_logger("price_service")


async def sync_prices_from_xml(
    db: AsyncSession,
    parsed_goods: list[ParsedGoodPrice],
    session: PriceImportSession,
) -> PriceImportSession:
    # Load price types
    result = await db.execute(select(PriceType))
    price_types = {pt.code: pt.id for pt in result.scalars().all()}

    # Load all products by SKU
    result = await db.execute(select(Product))
    products_by_sku: dict[str, Product] = {}
    for p in result.scalars().all():
        products_by_sku[p.sku] = p

    # Load existing product prices
    result = await db.execute(select(ProductPrice))
    existing_prices: dict[tuple[str, str], ProductPrice] = {}
    for pp in result.scalars().all():
        existing_prices[(pp.product_id, pp.price_type_id)] = pp

    session.total_goods = len(parsed_goods)

    for good in parsed_goods:
        product = products_by_sku.get(good.article)
        if not product:
            session.skipped += 1
            continue

        session.matched += 1

        for price_code, new_price_kopecks in good.prices.items():
            pt_id = price_types.get(price_code)
            if not pt_id:
                continue

            key = (product.id, pt_id)
            existing = existing_prices.get(key)

            if new_price_kopecks is not None:
                if existing:
                    if existing.price != new_price_kopecks:
                        old_price = existing.price
                        existing.price = new_price_kopecks
                        existing.updated_at = datetime.now(UTC)
                        session.updated += 1
                        db.add(PriceImportLog(
                            session_id=session.id, sku=good.article, product_id=product.id,
                            price_type=price_code, old_price=old_price, new_price=new_price_kopecks,
                            action="updated",
                        ))
                    else:
                        session.skipped += 1
                else:
                    pp = ProductPrice(
                        product_id=product.id, price_type_id=pt_id,
                        price=new_price_kopecks, currency="643",
                        updated_at=datetime.now(UTC),
                    )
                    db.add(pp)
                    existing_prices[key] = pp
                    session.created += 1
                    db.add(PriceImportLog(
                        session_id=session.id, sku=good.article, product_id=product.id,
                        price_type=price_code, old_price=None, new_price=new_price_kopecks,
                        action="created",
                    ))

                # Update Product.price when trade price changes
                if price_code == "trade":
                    product.price = new_price_kopecks
            else:
                # Price is None — delete if exists
                if existing:
                    old_price = existing.price
                    await db.delete(existing)
                    del existing_prices[key]
                    session.deleted += 1
                    db.add(PriceImportLog(
                        session_id=session.id, sku=good.article, product_id=product.id,
                        price_type=price_code, old_price=old_price, new_price=None,
                        action="deleted",
                    ))

    session.status = "completed"
    session.finished_at = datetime.now(UTC)
    await db.commit()

    logger.info("price_sync_completed",
                total=session.total_goods, matched=session.matched,
                updated=session.updated, created=session.created,
                deleted=session.deleted, skipped=session.skipped)
    return session


async def get_product_prices(db: AsyncSession, sku: str) -> list[dict]:
    result = await db.execute(
        select(ProductPrice, PriceType, Product)
        .join(PriceType, ProductPrice.price_type_id == PriceType.id)
        .join(Product, ProductPrice.product_id == Product.id)
        .where(Product.sku == sku)
    )
    prices = []
    for pp, pt, _ in result.all():
        prices.append({
            "price_type": pt.code,
            "price_type_label": pt.label,
            "price": pp.price,
            "price_rub": pp.price / 100,
            "currency": pp.currency,
            "updated_at": pp.updated_at.isoformat() if pp.updated_at else None,
        })
    return prices


async def get_import_sessions(db: AsyncSession, limit: int = 20) -> list[PriceImportSession]:
    result = await db.execute(
        select(PriceImportSession).order_by(PriceImportSession.started_at.desc()).limit(limit)
    )
    return list(result.scalars().all())


async def get_session_details(db: AsyncSession, session_id: str) -> dict | None:
    result = await db.execute(select(PriceImportSession).where(PriceImportSession.id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        return None

    logs_result = await db.execute(
        select(PriceImportLog).where(PriceImportLog.session_id == session_id).order_by(PriceImportLog.created_at)
    )
    logs = logs_result.scalars().all()

    return {
        "session": {
            "id": session.id, "file_name": session.file_name, "status": session.status,
            "started_at": session.started_at.isoformat() if session.started_at else None,
            "finished_at": session.finished_at.isoformat() if session.finished_at else None,
            "total_goods": session.total_goods, "matched": session.matched,
            "updated": session.updated, "created": session.created,
            "deleted": session.deleted, "skipped": session.skipped,
            "errors": session.errors, "error_message": session.error_message,
        },
        "logs": [
            {"sku": l.sku, "price_type": l.price_type, "old_price": l.old_price,
             "new_price": l.new_price, "action": l.action}
            for l in logs
        ],
    }


async def cleanup_old_sessions(db: AsyncSession, retention_days: int) -> int:
    cutoff = datetime.now(UTC) - timedelta(days=retention_days)
    # Delete logs first (cascade may handle this, but be explicit)
    old_sessions = await db.execute(
        select(PriceImportSession.id).where(PriceImportSession.started_at < cutoff)
    )
    old_ids = [row[0] for row in old_sessions.all()]
    if not old_ids:
        return 0
    await db.execute(delete(PriceImportLog).where(PriceImportLog.session_id.in_(old_ids)))
    await db.execute(delete(PriceImportSession).where(PriceImportSession.id.in_(old_ids)))
    await db.commit()
    logger.info("price_journals_cleaned", deleted_sessions=len(old_ids))
    return len(old_ids)
