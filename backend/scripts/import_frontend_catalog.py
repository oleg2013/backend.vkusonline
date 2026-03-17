"""
Import frontend catalog (catalog.ts) into the backend database.

This script parses the TypeScript catalog file from the frontend repository,
extracts all product data, and writes it into the `products` table.

Usage (on the server via SSH):
    cd /opt/vkus-backend/backend
    python -m scripts.import_frontend_catalog --catalog-path /tmp/catalog.ts --clean
    python -m scripts.import_frontend_catalog --catalog-path /tmp/catalog.ts --upsert
    python -m scripts.import_frontend_catalog --catalog-path /tmp/catalog.ts --dry-run

Flags:
    --catalog-path  Path to catalog.ts (required)
    --clean         Delete all existing products before import
    --upsert        Update existing products (by SKU) instead of skipping
    --dry-run       Parse and display results without writing to DB
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import re
import sys
from pathlib import Path

import structlog

# ---------------------------------------------------------------------------
#  Weight string parser
# ---------------------------------------------------------------------------

# Pattern: "50 пакетиков по 2.5 грамма" or "20 пирамидок по 1.75 грамма"
_MULTI_PACK_RE = re.compile(
    r"(\d+)\s*(?:пакетик|пирамидок|пирамидки)\w*\s+по\s+([\d.,]+)\s*(?:грамм|г)",
    re.IGNORECASE,
)

# Pattern: "450 г (104 пирамидки)" or "160 г (26 пирамидок)"
_WEIGHT_PAREN_RE = re.compile(
    r"(\d+)\s*(?:грамм|г)\b",
    re.IGNORECASE,
)

# Simple pattern: "120 грамм" or "1000 г"
_SIMPLE_WEIGHT_RE = re.compile(
    r"(\d+)\s*(?:грамм|г)\b",
    re.IGNORECASE,
)


def parse_weight_grams(s: str) -> int:
    """Parse a Russian weight string into grams.

    Examples:
        "120 грамм"                  → 120
        "1000 г"                     → 1000
        "50 пакетиков по 2.5 грамма" → 125
        "20 пирамидок по 1.75 грамма"→ 35
        "450 г (104 пирамидки)"      → 450
        "160 г (26 пирамидок)"       → 160
    """
    if not s:
        return 0

    # Try multi-pack first: "50 пакетиков по 2.5 грамма"
    m = _MULTI_PACK_RE.search(s)
    if m:
        count = int(m.group(1))
        per_item = float(m.group(2).replace(",", "."))
        return int(math.ceil(count * per_item))

    # Try simple weight (first number + г/грамм)
    m = _SIMPLE_WEIGHT_RE.search(s)
    if m:
        return int(m.group(1))

    return 0


# ---------------------------------------------------------------------------
#  TypeScript object parser
# ---------------------------------------------------------------------------

def _extract_string_field(obj_text: str, field: str) -> str | None:
    """Extract a string field value from a TS object literal."""
    # Match: field: "value" or field: 'value'
    pattern = re.compile(
        rf'{field}\s*:\s*["\']([^"\']*)["\']',
        re.DOTALL,
    )
    m = pattern.search(obj_text)
    if m:
        return m.group(1)

    # Match multiline template strings: field: "...\n..."
    # Already handled by [^"']* which doesn't cross quotes
    return None


def _extract_multiline_string_field(obj_text: str, field: str) -> str | None:
    """Extract a string field that may span multiple lines (description, composition)."""
    # Handles both single-quoted and double-quoted, including escaped newlines
    pattern = re.compile(
        rf"""{field}\s*:\s*(['"])(.*?)\1""",
        re.DOTALL,
    )
    m = pattern.search(obj_text)
    if m:
        val = m.group(2)
        # Unescape literal \n
        val = val.replace("\\n", "\n")
        return val.strip()
    return None


def _extract_number_field(obj_text: str, field: str) -> float | None:
    """Extract a numeric field value."""
    pattern = re.compile(rf"{field}\s*:\s*([\d.]+)")
    m = pattern.search(obj_text)
    if m:
        return float(m.group(1))
    return None


def _extract_string_array(obj_text: str, field: str) -> list[str]:
    """Extract an array of strings like: field: ["a", "b", "c"]."""
    pattern = re.compile(rf"{field}\s*:\s*\[(.*?)\]", re.DOTALL)
    m = pattern.search(obj_text)
    if not m:
        return []
    inner = m.group(1)
    items = re.findall(r'["\']([^"\']+)["\']', inner)
    return items


def _split_ts_objects(array_text: str) -> list[str]:
    """Split a TypeScript array of objects into individual object strings.

    Uses brace counting to handle nested objects/arrays.
    """
    objects = []
    depth = 0
    start = None

    for i, ch in enumerate(array_text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start is not None:
                objects.append(array_text[start : i + 1])
                start = None

    return objects


def parse_catalog_ts(catalog_path: str) -> list[dict]:
    """Parse catalog.ts and return a list of product dicts."""
    text = Path(catalog_path).read_text(encoding="utf-8")

    # Find the PRODUCTS_DB array
    # Pattern: export const PRODUCTS_DB: CatalogProduct[] = [...]
    m = re.search(
        r"(?:export\s+)?const\s+PRODUCTS_DB\s*(?::\s*\w+(?:\[\])?\s*)?=\s*\[",
        text,
    )
    if not m:
        raise ValueError("Cannot find PRODUCTS_DB array in catalog.ts")

    # Find the matching closing bracket
    start = m.end() - 1  # position of '['
    depth = 0
    end = start
    for i in range(start, len(text)):
        if text[i] == "[":
            depth += 1
        elif text[i] == "]":
            depth -= 1
            if depth == 0:
                end = i + 1
                break

    array_text = text[start:end]
    object_strings = _split_ts_objects(array_text)

    products = []
    for obj_text in object_strings:
        # Use sku field preferentially, fall back to id
        sku = _extract_string_field(obj_text, "sku")
        if not sku:
            sku = _extract_string_field(obj_text, "id")
        if not sku:
            continue

        title = _extract_string_field(obj_text, "title") or ""
        price_rub = _extract_number_field(obj_text, "price")
        weight_str = _extract_string_field(obj_text, "weight") or ""
        product_type = _extract_string_field(obj_text, "type")
        sub_type = _extract_string_field(obj_text, "subType")
        product_format = _extract_string_field(obj_text, "format")
        description = _extract_multiline_string_field(obj_text, "description")
        composition = _extract_multiline_string_field(obj_text, "composition")
        taste = _extract_string_array(obj_text, "taste")
        images = _extract_string_array(obj_text, "images")

        weight_grams = parse_weight_grams(weight_str)
        price_kopecks = int(price_rub * 100) if price_rub else 0

        products.append({
            "sku": sku,
            "name": title,
            "price": price_kopecks,
            "weight_grams": weight_grams,
            "product_type": product_type,
            "sub_type": sub_type,
            "product_format": product_format,
            "description": description,
            "composition": composition,
            "taste": taste,
            "images": images,
            "vat_rate": 20,
            "is_active": True,
        })

    return products


# ---------------------------------------------------------------------------
#  Database operations
# ---------------------------------------------------------------------------

async def import_to_db(
    products: list[dict],
    *,
    clean: bool = False,
    upsert: bool = False,
) -> dict:
    """Import parsed products into the database.

    Returns stats dict with counts.
    """
    from packages.core.db import async_session_factory
    from packages.models.catalog import Product

    stats = {"created": 0, "updated": 0, "skipped": 0, "deleted": 0}

    async with async_session_factory() as db:
        if clean:
            from sqlalchemy import delete

            result = await db.execute(delete(Product))
            stats["deleted"] = result.rowcount
            logger.info("import.cleaned_products", deleted=stats["deleted"])

        from sqlalchemy import select

        for p in products:
            # Check if product already exists
            stmt = select(Product).where(Product.sku == p["sku"])
            result = await db.execute(stmt)
            existing = result.scalar_one_or_none()

            if existing:
                if upsert:
                    # Update all fields
                    existing.name = p["name"]
                    existing.price = p["price"]
                    existing.weight_grams = p["weight_grams"]
                    existing.product_type = p["product_type"]
                    existing.sub_type = p["sub_type"]
                    existing.product_format = p["product_format"]
                    existing.description = p["description"]
                    existing.composition = p["composition"]
                    existing.taste = p["taste"]
                    existing.images = p["images"]
                    existing.vat_rate = p["vat_rate"]
                    existing.is_active = p["is_active"]
                    stats["updated"] += 1
                else:
                    stats["skipped"] += 1
            else:
                new_product = Product(
                    sku=p["sku"],
                    name=p["name"],
                    price=p["price"],
                    weight_grams=p["weight_grams"],
                    product_type=p["product_type"],
                    sub_type=p["sub_type"],
                    product_format=p["product_format"],
                    description=p["description"],
                    composition=p["composition"],
                    taste=p["taste"],
                    images=p["images"],
                    vat_rate=p["vat_rate"],
                    is_active=p["is_active"],
                    family_id=None,
                    sort_order=0,
                )
                db.add(new_product)
                stats["created"] += 1

        await db.commit()

    return stats


# ---------------------------------------------------------------------------
#  CLI entry point
# ---------------------------------------------------------------------------

logger = structlog.get_logger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Import frontend catalog.ts into backend database",
    )
    parser.add_argument(
        "--catalog-path",
        required=True,
        help="Path to frontend catalog.ts file",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Delete all existing products before import",
    )
    parser.add_argument(
        "--upsert",
        action="store_true",
        help="Update existing products (by SKU) instead of skipping",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and display results without writing to DB",
    )
    args = parser.parse_args()

    # Validate catalog path
    catalog_path = Path(args.catalog_path)
    if not catalog_path.exists():
        print(f"ERROR: File not found: {catalog_path}")
        sys.exit(1)

    print(f"Parsing: {catalog_path}")
    products = parse_catalog_ts(str(catalog_path))
    print(f"Parsed: {len(products)} products")

    if not products:
        print("ERROR: No products found in catalog.ts")
        sys.exit(1)

    # Display summary table
    print(f"\n{'SKU':<12} {'Price':>8} {'Weight':>8} {'Type':<12} {'Name'}")
    print("-" * 80)
    for p in products:
        price_rub = p["price"] / 100
        print(
            f"{p['sku']:<12} {price_rub:>7.0f}₽ {p['weight_grams']:>6}g "
            f"{(p['product_type'] or '?'):<12} {p['name'][:40]}"
        )

    # Show type distribution
    types = {}
    for p in products:
        t = p.get("product_type") or "unknown"
        types[t] = types.get(t, 0) + 1
    print(f"\nType distribution: {types}")

    # Show weight issues
    zero_weight = [p for p in products if p["weight_grams"] == 0]
    if zero_weight:
        print(f"\nWARNING: {len(zero_weight)} products with weight=0:")
        for p in zero_weight:
            print(f"  {p['sku']}: {p['name']}")

    # Show image counts
    no_images = [p for p in products if not p["images"]]
    if no_images:
        print(f"\nWARNING: {len(no_images)} products without images")

    if args.dry_run:
        print("\n[DRY RUN] No database changes made.")
        # Print detailed JSON for first 3 products
        print("\nSample product (full data):")
        sample = products[0]
        print(json.dumps(sample, ensure_ascii=False, indent=2))
        return

    # Import to database
    print(f"\nImporting to database... (clean={args.clean}, upsert={args.upsert})")
    stats = asyncio.run(import_to_db(products, clean=args.clean, upsert=args.upsert))
    print(f"\nImport complete:")
    print(f"  Created:  {stats['created']}")
    print(f"  Updated:  {stats['updated']}")
    print(f"  Skipped:  {stats['skipped']}")
    print(f"  Deleted:  {stats['deleted']}")
    print(f"\nTotal products in catalog: {len(products)}")


if __name__ == "__main__":
    main()
