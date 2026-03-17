from __future__ import annotations

import structlog
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import attributes, selectinload

from packages.core.exceptions import NotFoundError, ValidationError
from packages.enums import CartOwnerType
from packages.models.cart import Cart, CartItem
from packages.models.catalog import Product

logger = structlog.get_logger(__name__)


async def get_or_create_cart(
    db: AsyncSession,
    owner_type: CartOwnerType,
    owner_id: str,
) -> Cart:
    if owner_type == CartOwnerType.GUEST:
        stmt = select(Cart).where(
            Cart.owner_type == "guest",
            Cart.guest_session_id == owner_id,
        ).options(selectinload(Cart.items))
    else:
        stmt = select(Cart).where(
            Cart.owner_type == "user",
            Cart.user_id == owner_id,
        ).options(selectinload(Cart.items))

    result = await db.execute(stmt)
    cart = result.scalar_one_or_none()

    if cart:
        return cart

    cart = Cart(
        owner_type=owner_type.value,
        guest_session_id=owner_id if owner_type == CartOwnerType.GUEST else None,
        user_id=owner_id if owner_type == CartOwnerType.USER else None,
    )
    db.add(cart)
    await db.flush()
    attributes.set_committed_value(cart, "items", [])
    return cart


async def set_cart_items(
    db: AsyncSession,
    cart: Cart,
    items: list[dict],
) -> Cart:
    # Clear existing items
    await db.execute(delete(CartItem).where(CartItem.cart_id == cart.id))

    new_items = []
    for item_data in items:
        product = await _get_product(db, item_data["product_sku"])
        if not product:
            raise NotFoundError("Product", item_data["product_sku"])

        quantity = item_data.get("quantity", 1)
        if quantity < 1:
            raise ValidationError(f"Quantity must be >= 1 for {item_data['product_sku']}")

        ci = CartItem(
            cart_id=cart.id,
            product_sku=product.sku,
            quantity=quantity,
            price_snapshot=product.price,
        )
        db.add(ci)
        new_items.append(ci)

    await db.flush()
    attributes.set_committed_value(cart, "items", new_items)
    return cart


async def update_cart_item(
    db: AsyncSession,
    cart: Cart,
    item_id: str,
    quantity: int,
) -> CartItem:
    stmt = select(CartItem).where(CartItem.id == item_id, CartItem.cart_id == cart.id)
    result = await db.execute(stmt)
    item = result.scalar_one_or_none()

    if not item:
        raise NotFoundError("Cart item", item_id)

    if quantity < 1:
        raise ValidationError("Quantity must be >= 1")

    item.quantity = quantity
    await db.flush()
    return item


async def remove_cart_item(
    db: AsyncSession,
    cart: Cart,
    item_id: str,
) -> None:
    stmt = select(CartItem).where(CartItem.id == item_id, CartItem.cart_id == cart.id)
    result = await db.execute(stmt)
    item = result.scalar_one_or_none()

    if not item:
        raise NotFoundError("Cart item", item_id)

    await db.delete(item)
    await db.flush()


async def clear_cart(
    db: AsyncSession,
    cart: Cart,
) -> None:
    await db.execute(delete(CartItem).where(CartItem.cart_id == cart.id))
    await db.flush()
    cart.items = []


async def merge_guest_cart_to_user(
    db: AsyncSession,
    guest_session_id: str,
    user_id: str,
) -> None:
    guest_cart_stmt = select(Cart).where(
        Cart.owner_type == "guest",
        Cart.guest_session_id == guest_session_id,
    ).options(selectinload(Cart.items))
    guest_result = await db.execute(guest_cart_stmt)
    guest_cart = guest_result.scalar_one_or_none()

    if not guest_cart or not guest_cart.items:
        return

    user_cart = await get_or_create_cart(db, CartOwnerType.USER, user_id)

    existing_skus = {item.product_sku: item for item in user_cart.items}
    for guest_item in guest_cart.items:
        if guest_item.product_sku in existing_skus:
            existing_skus[guest_item.product_sku].quantity += guest_item.quantity
        else:
            new_item = CartItem(
                cart_id=user_cart.id,
                product_sku=guest_item.product_sku,
                quantity=guest_item.quantity,
                price_snapshot=guest_item.price_snapshot,
            )
            db.add(new_item)

    await clear_cart(db, guest_cart)
    await db.flush()
    logger.info("cart_merged", guest_session_id=guest_session_id, user_id=user_id)


async def _get_product(db: AsyncSession, sku: str) -> Product | None:
    stmt = select(Product).where(Product.sku == sku, Product.is_active.is_(True))
    result = await db.execute(stmt)
    return result.scalar_one_or_none()
