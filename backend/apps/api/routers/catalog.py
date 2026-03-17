from __future__ import annotations

from fastapi import APIRouter, Query

from apps.api.deps import DbSession, RequestId
from packages.core.exceptions import NotFoundError
from packages.services import catalog as catalog_service

router = APIRouter(prefix="/catalog", tags=["catalog"])


@router.get("/families")
async def list_families(db: DbSession, request_id: RequestId):
    families = await catalog_service.get_families(db)
    data = []
    for f in families:
        data.append({
            "id": f.id,
            "slug": f.slug,
            "name": f.name,
            "category": f.category,
            "subcategory": f.subcategory,
            "description": f.description,
            "image_url": f.image_url,
            "tags": f.tags,
            "products": [
                {
                    "sku": p.sku,
                    "name": p.name,
                    "variant_label": p.variant_label,
                    "price": p.price / 100,
                    "weight_grams": p.weight_grams,
                }
                for p in f.products
                if p.is_active
            ],
        })
    return {"ok": True, "data": data, "request_id": request_id}


@router.get("/products")
async def list_products(
    db: DbSession,
    request_id: RequestId,
    category: str | None = Query(None),
    family: str | None = Query(None),
):
    products = await catalog_service.get_products(db, category=category, family_slug=family)
    data = [
        {
            "sku": p.sku,
            "name": p.name,
            "variant_label": p.variant_label,
            "price": p.price / 100,
            "weight_grams": p.weight_grams,
            "vat_rate": p.vat_rate,
            "is_active": p.is_active,
            "product_type": p.product_type,
            "sub_type": p.sub_type,
            "product_format": p.product_format,
            "description": p.description,
            "composition": p.composition,
            "taste": p.taste,
            "images": p.images,
        }
        for p in products
    ]
    return {"ok": True, "data": data, "request_id": request_id}


@router.get("/products/{sku}")
async def get_product(sku: str, db: DbSession, request_id: RequestId):
    product = await catalog_service.get_product_by_sku(db, sku)
    if not product:
        raise NotFoundError("Product", sku)
    return {
        "ok": True,
        "data": {
            "sku": product.sku,
            "name": product.name,
            "variant_label": product.variant_label,
            "price": product.price / 100,
            "weight_grams": product.weight_grams,
            "vat_rate": product.vat_rate,
            "is_active": product.is_active,
            "dimensions_mm": product.dimensions_mm,
            "product_type": product.product_type,
            "sub_type": product.sub_type,
            "product_format": product.product_format,
            "description": product.description,
            "composition": product.composition,
            "taste": product.taste,
            "images": product.images,
        },
        "request_id": request_id,
    }


@router.get("/collections")
async def list_collections(request_id: RequestId):
    # TODO: implement collections from DB/seed
    return {"ok": True, "data": [], "request_id": request_id}
