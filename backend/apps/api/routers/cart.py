from __future__ import annotations

from fastapi import APIRouter

from apps.api.deps import CurrentUserId, DbSession, GuestSessionId, RequestId
from packages.enums import CartOwnerType
from packages.schemas.cart import CartItemAdd, CartItemUpdate
from packages.services import cart as cart_service
from packages.services import guests as guest_service

router = APIRouter(tags=["cart"])


def _cart_response(cart, request_id):
    items = []
    subtotal = 0
    for item in cart.items:
        total = item.price_snapshot * item.quantity
        subtotal += total
        items.append({
            "id": item.id,
            "product_sku": item.product_sku,
            "quantity": item.quantity,
            "unit_price": item.price_snapshot / 100,
            "total_price": total / 100,
        })
    return {
        "ok": True,
        "data": {
            "id": cart.id,
            "items": items,
            "subtotal": subtotal / 100,
            "items_count": len(items),
        },
        "request_id": request_id,
    }


# === Guest Cart ===

@router.get("/guest/cart")
async def get_guest_cart(
    guest_session_id: GuestSessionId,
    db: DbSession,
    request_id: RequestId,
):
    await guest_service.validate_guest_session(db, guest_session_id)
    cart = await cart_service.get_or_create_cart(db, CartOwnerType.GUEST, guest_session_id)
    return _cart_response(cart, request_id)


@router.put("/guest/cart/items")
async def set_guest_cart_items(
    items: list[CartItemAdd],
    guest_session_id: GuestSessionId,
    db: DbSession,
    request_id: RequestId,
):
    await guest_service.validate_guest_session(db, guest_session_id)
    cart = await cart_service.get_or_create_cart(db, CartOwnerType.GUEST, guest_session_id)
    cart = await cart_service.set_cart_items(
        db, cart, [i.model_dump() for i in items]
    )
    return _cart_response(cart, request_id)


@router.patch("/guest/cart/items/{item_id}")
async def update_guest_cart_item(
    item_id: str,
    body: CartItemUpdate,
    guest_session_id: GuestSessionId,
    db: DbSession,
    request_id: RequestId,
):
    await guest_service.validate_guest_session(db, guest_session_id)
    cart = await cart_service.get_or_create_cart(db, CartOwnerType.GUEST, guest_session_id)
    await cart_service.update_cart_item(db, cart, item_id, body.quantity)
    cart = await cart_service.get_or_create_cart(db, CartOwnerType.GUEST, guest_session_id)
    return _cart_response(cart, request_id)


@router.delete("/guest/cart/items/{item_id}")
async def delete_guest_cart_item(
    item_id: str,
    guest_session_id: GuestSessionId,
    db: DbSession,
    request_id: RequestId,
):
    await guest_service.validate_guest_session(db, guest_session_id)
    cart = await cart_service.get_or_create_cart(db, CartOwnerType.GUEST, guest_session_id)
    await cart_service.remove_cart_item(db, cart, item_id)
    return {"ok": True, "data": {"message": "Item removed"}, "request_id": request_id}


@router.delete("/guest/cart")
async def clear_guest_cart(
    guest_session_id: GuestSessionId,
    db: DbSession,
    request_id: RequestId,
):
    await guest_service.validate_guest_session(db, guest_session_id)
    cart = await cart_service.get_or_create_cart(db, CartOwnerType.GUEST, guest_session_id)
    await cart_service.clear_cart(db, cart)
    return {"ok": True, "data": {"message": "Cart cleared"}, "request_id": request_id}


# === User Cart ===

@router.get("/me/cart")
async def get_user_cart(
    user_id: CurrentUserId,
    db: DbSession,
    request_id: RequestId,
):
    cart = await cart_service.get_or_create_cart(db, CartOwnerType.USER, user_id)
    return _cart_response(cart, request_id)


@router.put("/me/cart/items")
async def set_user_cart_items(
    items: list[CartItemAdd],
    user_id: CurrentUserId,
    db: DbSession,
    request_id: RequestId,
):
    cart = await cart_service.get_or_create_cart(db, CartOwnerType.USER, user_id)
    cart = await cart_service.set_cart_items(
        db, cart, [i.model_dump() for i in items]
    )
    return _cart_response(cart, request_id)


@router.patch("/me/cart/items/{item_id}")
async def update_user_cart_item(
    item_id: str,
    body: CartItemUpdate,
    user_id: CurrentUserId,
    db: DbSession,
    request_id: RequestId,
):
    cart = await cart_service.get_or_create_cart(db, CartOwnerType.USER, user_id)
    await cart_service.update_cart_item(db, cart, item_id, body.quantity)
    cart = await cart_service.get_or_create_cart(db, CartOwnerType.USER, user_id)
    return _cart_response(cart, request_id)


@router.delete("/me/cart/items/{item_id}")
async def delete_user_cart_item(
    item_id: str,
    user_id: CurrentUserId,
    db: DbSession,
    request_id: RequestId,
):
    cart = await cart_service.get_or_create_cart(db, CartOwnerType.USER, user_id)
    await cart_service.remove_cart_item(db, cart, item_id)
    return {"ok": True, "data": {"message": "Item removed"}, "request_id": request_id}
