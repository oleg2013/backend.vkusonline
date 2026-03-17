"""Seed the catalog with sample tea and coffee products.

Usage:
    python -m scripts.seed_catalog
"""

from __future__ import annotations

import asyncio
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from packages.core.config import settings
from packages.models.catalog import Product, ProductFamily

# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------

CATALOG: list[dict] = [
    # ── Tea ────────────────────────────────────────────────────────────
    {
        "slug": "jasmine-green",
        "name": "Жасминовый зелёный чай",
        "category": "tea",
        "subcategory": "green",
        "description": "Классический китайский зелёный чай с натуральным жасмином. "
        "Мягкий цветочный аромат и освежающий вкус.",
        "variants": [
            {"label": "50 г", "weight": 50, "price": 45000},
            {"label": "100 г", "weight": 100, "price": 82000},
            {"label": "250 г", "weight": 250, "price": 189000},
        ],
    },
    {
        "slug": "earl-grey-classic",
        "name": "Эрл Грей классический",
        "category": "tea",
        "subcategory": "black",
        "description": "Цейлонский чёрный чай с маслом бергамота. "
        "Бодрящий аромат и насыщенный вкус.",
        "variants": [
            {"label": "50 г", "weight": 50, "price": 39000},
            {"label": "100 г", "weight": 100, "price": 72000},
            {"label": "250 г", "weight": 250, "price": 165000},
        ],
    },
    {
        "slug": "da-hong-pao",
        "name": "Да Хун Пао",
        "category": "tea",
        "subcategory": "oolong",
        "description": "Легендарный утёсный улун из провинции Фуцзянь. "
        "Глубокий карамельно-минеральный вкус с долгим послевкусием.",
        "variants": [
            {"label": "50 г", "weight": 50, "price": 89000},
            {"label": "100 г", "weight": 100, "price": 165000},
        ],
    },
    {
        "slug": "tie-guan-yin",
        "name": "Те Гуань Инь",
        "category": "tea",
        "subcategory": "oolong",
        "description": "Светлый улун с орхидеевым ароматом и сливочным послевкусием. "
        "Провинция Фуцзянь, Китай.",
        "variants": [
            {"label": "50 г", "weight": 50, "price": 75000},
            {"label": "100 г", "weight": 100, "price": 139000},
            {"label": "250 г", "weight": 250, "price": 319000},
        ],
    },
    {
        "slug": "sencha-premium",
        "name": "Сенча Премиум",
        "category": "tea",
        "subcategory": "green",
        "description": "Японский зелёный чай первого сбора. "
        "Свежий травянистый аромат и лёгкая сладость.",
        "variants": [
            {"label": "50 г", "weight": 50, "price": 62000},
            {"label": "100 г", "weight": 100, "price": 115000},
        ],
    },
    # ── Coffee ─────────────────────────────────────────────────────────
    {
        "slug": "brazil-santos",
        "name": "Бразилия Сантос",
        "category": "coffee",
        "subcategory": "arabica",
        "description": "Мягкий бразильский кофе с ореховыми нотами и лёгкой кислинкой. "
        "Средняя обжарка.",
        "variants": [
            {"label": "100 г, зерно", "weight": 100, "price": 49000},
            {"label": "250 г, зерно", "weight": 250, "price": 112000},
            {"label": "250 г, молотый", "weight": 250, "price": 119000},
        ],
    },
    {
        "slug": "ethiopia-yirgacheffe",
        "name": "Эфиопия Иргачеффе",
        "category": "coffee",
        "subcategory": "arabica",
        "description": "Яркий эфиопский кофе с цитрусовыми и цветочными нотами. "
        "Светлая обжарка.",
        "variants": [
            {"label": "100 г, зерно", "weight": 100, "price": 65000},
            {"label": "250 г, зерно", "weight": 250, "price": 149000},
            {"label": "250 г, молотый", "weight": 250, "price": 155000},
        ],
    },
    {
        "slug": "colombia-supremo",
        "name": "Колумбия Супремо",
        "category": "coffee",
        "subcategory": "arabica",
        "description": "Сбалансированный колумбийский кофе с карамельной сладостью "
        "и нотами тёмного шоколада. Средняя обжарка.",
        "variants": [
            {"label": "100 г, зерно", "weight": 100, "price": 55000},
            {"label": "250 г, зерно", "weight": 250, "price": 125000},
        ],
    },
    {
        "slug": "kenya-aa",
        "name": "Кения АА",
        "category": "coffee",
        "subcategory": "arabica",
        "description": "Высокогорный кенийский кофе с выраженной кислотностью, "
        "ягодными нотами и плотным телом. Средне-светлая обжарка.",
        "variants": [
            {"label": "100 г, зерно", "weight": 100, "price": 72000},
            {"label": "250 г, зерно", "weight": 250, "price": 165000},
            {"label": "250 г, молотый", "weight": 250, "price": 172000},
        ],
    },
    {
        "slug": "guatemala-antigua",
        "name": "Гватемала Антигуа",
        "category": "coffee",
        "subcategory": "arabica",
        "description": "Кофе вулканического региона Антигуа. "
        "Дымные и шоколадные ноты, пряное послевкусие. Средне-тёмная обжарка.",
        "variants": [
            {"label": "100 г, зерно", "weight": 100, "price": 59000},
            {"label": "250 г, зерно", "weight": 250, "price": 135000},
        ],
    },
]


def _make_sku(family_slug: str, idx: int) -> str:
    """Generate a deterministic SKU from the family slug and variant index."""
    prefix = family_slug.upper().replace("-", "")[:8]
    return f"{prefix}-{idx + 1:03d}"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def seed() -> None:
    engine = create_async_engine(settings.database_url, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as session:
        for family_data in CATALOG:
            # Check if family already exists
            stmt = select(ProductFamily).where(ProductFamily.slug == family_data["slug"])
            result = await session.execute(stmt)
            existing = result.scalar_one_or_none()

            if existing is not None:
                print(f"  skip  {family_data['slug']} (already exists)")
                continue

            family = ProductFamily(
                id=str(uuid.uuid4()),
                slug=family_data["slug"],
                name=family_data["name"],
                category=family_data["category"],
                subcategory=family_data.get("subcategory"),
                description=family_data.get("description"),
                is_active=True,
            )
            session.add(family)

            for idx, variant in enumerate(family_data["variants"]):
                product = Product(
                    id=str(uuid.uuid4()),
                    sku=_make_sku(family_data["slug"], idx),
                    family_id=family.id,
                    name=f"{family_data['name']} ({variant['label']})",
                    variant_label=variant["label"],
                    price=variant["price"],
                    weight_grams=variant["weight"],
                    vat_rate=20,
                    is_active=True,
                    sort_order=idx,
                )
                session.add(product)

            print(f"  added {family_data['slug']} ({len(family_data['variants'])} variants)")

        await session.commit()

    await engine.dispose()
    print("\nDone. Catalog seeded successfully.")


if __name__ == "__main__":
    asyncio.run(seed())
