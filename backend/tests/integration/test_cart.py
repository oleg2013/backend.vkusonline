"""Integration tests for the cart service."""

from __future__ import annotations

import pytest

from packages.core.exceptions import NotFoundError, ValidationError
from packages.enums import CartOwnerType
from packages.services.cart import (
    clear_cart,
    get_or_create_cart,
    merge_guest_cart_to_user,
    remove_cart_item,
    set_cart_items,
    update_cart_item,
)


class TestGetOrCreateCart:
    """Tests for get_or_create_cart."""

    @pytest.mark.asyncio
    async def test_creates_empty_cart(self, db_session, sample_guest_session):
        cart = await get_or_create_cart(
            db_session, CartOwnerType.GUEST, sample_guest_session.id
        )

        assert cart is not None, "should return a cart"
        assert cart.owner_type == "guest"
        assert cart.guest_session_id == sample_guest_session.id
        assert len(cart.items) == 0, "new cart should have no items"

    @pytest.mark.asyncio
    async def test_returns_existing_cart(self, db_session, sample_guest_session):
        cart1 = await get_or_create_cart(
            db_session, CartOwnerType.GUEST, sample_guest_session.id
        )
        cart2 = await get_or_create_cart(
            db_session, CartOwnerType.GUEST, sample_guest_session.id
        )

        assert cart1.id == cart2.id, "should return the same cart on second call"

    @pytest.mark.asyncio
    async def test_creates_user_cart(self, db_session, sample_user):
        cart = await get_or_create_cart(
            db_session, CartOwnerType.USER, sample_user.id
        )

        assert cart.owner_type == "user"
        assert cart.user_id == sample_user.id


class TestSetCartItems:
    """Tests for set_cart_items."""

    @pytest.mark.asyncio
    async def test_set_items_with_valid_products(self, db_session, sample_guest_session, sample_product):
        cart = await get_or_create_cart(
            db_session, CartOwnerType.GUEST, sample_guest_session.id
        )

        items = [
            {"product_sku": sample_product.sku, "quantity": 3},
        ]
        updated_cart = await set_cart_items(db_session, cart, items)

        assert len(updated_cart.items) == 1, "cart should have 1 item"
        assert updated_cart.items[0].product_sku == sample_product.sku
        assert updated_cart.items[0].quantity == 3
        assert updated_cart.items[0].price_snapshot == sample_product.price

    @pytest.mark.asyncio
    async def test_set_items_with_invalid_sku_fails(self, db_session, sample_guest_session):
        cart = await get_or_create_cart(
            db_session, CartOwnerType.GUEST, sample_guest_session.id
        )

        items = [
            {"product_sku": "NONEXISTENT-SKU", "quantity": 1},
        ]
        with pytest.raises(NotFoundError, match="Product"):
            await set_cart_items(db_session, cart, items)

    @pytest.mark.asyncio
    async def test_set_items_replaces_existing(self, db_session, sample_guest_session, sample_product):
        cart = await get_or_create_cart(
            db_session, CartOwnerType.GUEST, sample_guest_session.id
        )

        # Set initial items
        await set_cart_items(db_session, cart, [
            {"product_sku": sample_product.sku, "quantity": 2},
        ])

        # Replace with new items
        updated = await set_cart_items(db_session, cart, [
            {"product_sku": sample_product.sku, "quantity": 5},
        ])

        assert len(updated.items) == 1
        assert updated.items[0].quantity == 5, "quantity should be updated"


class TestUpdateCartItem:
    """Tests for update_cart_item."""

    @pytest.mark.asyncio
    async def test_update_changes_quantity(self, db_session, sample_cart):
        item = sample_cart.items[0]
        updated_item = await update_cart_item(
            db_session, sample_cart, item.id, quantity=10
        )

        assert updated_item.quantity == 10, "quantity should be updated to 10"

    @pytest.mark.asyncio
    async def test_update_nonexistent_item_fails(self, db_session, sample_cart):
        with pytest.raises(NotFoundError, match="Cart item"):
            await update_cart_item(
                db_session, sample_cart, "nonexistent-item-id", quantity=5
            )

    @pytest.mark.asyncio
    async def test_update_zero_quantity_fails(self, db_session, sample_cart):
        item = sample_cart.items[0]
        with pytest.raises(ValidationError, match="Quantity"):
            await update_cart_item(
                db_session, sample_cart, item.id, quantity=0
            )


class TestRemoveCartItem:
    """Tests for remove_cart_item."""

    @pytest.mark.asyncio
    async def test_remove_existing_item(self, db_session, sample_cart):
        item = sample_cart.items[0]
        await remove_cart_item(db_session, sample_cart, item.id)

        # Verify item is gone by trying to remove it again
        with pytest.raises(NotFoundError, match="Cart item"):
            await remove_cart_item(db_session, sample_cart, item.id)

    @pytest.mark.asyncio
    async def test_remove_nonexistent_item_fails(self, db_session, sample_cart):
        with pytest.raises(NotFoundError, match="Cart item"):
            await remove_cart_item(
                db_session, sample_cart, "nonexistent-item-id"
            )


class TestClearCart:
    """Tests for clear_cart."""

    @pytest.mark.asyncio
    async def test_clear_removes_all_items(self, db_session, sample_cart):
        assert len(sample_cart.items) > 0, "cart should have items before clearing"

        await clear_cart(db_session, sample_cart)

        assert len(sample_cart.items) == 0, "cart should have no items after clearing"


class TestMergeGuestCartToUser:
    """Tests for merge_guest_cart_to_user."""

    @pytest.mark.asyncio
    async def test_merge_items_to_user_cart(
        self, db_session, sample_guest_session, sample_product, sample_user
    ):
        # Create guest cart with items
        guest_cart = await get_or_create_cart(
            db_session, CartOwnerType.GUEST, sample_guest_session.id
        )
        await set_cart_items(db_session, guest_cart, [
            {"product_sku": sample_product.sku, "quantity": 2},
        ])

        # Merge to user
        await merge_guest_cart_to_user(
            db_session, sample_guest_session.id, sample_user.id
        )

        # Verify user cart has the items
        user_cart = await get_or_create_cart(
            db_session, CartOwnerType.USER, sample_user.id
        )
        assert len(user_cart.items) == 1, "user cart should have merged items"
        assert user_cart.items[0].product_sku == sample_product.sku
        assert user_cart.items[0].quantity == 2

    @pytest.mark.asyncio
    async def test_merge_handles_duplicate_skus(
        self, db_session, sample_guest_session, sample_product, sample_user
    ):
        # Create user cart with item
        user_cart = await get_or_create_cart(
            db_session, CartOwnerType.USER, sample_user.id
        )
        await set_cart_items(db_session, user_cart, [
            {"product_sku": sample_product.sku, "quantity": 1},
        ])

        # Create guest cart with same product
        guest_cart = await get_or_create_cart(
            db_session, CartOwnerType.GUEST, sample_guest_session.id
        )
        await set_cart_items(db_session, guest_cart, [
            {"product_sku": sample_product.sku, "quantity": 3},
        ])

        # Merge
        await merge_guest_cart_to_user(
            db_session, sample_guest_session.id, sample_user.id
        )

        # Reload user cart
        merged_cart = await get_or_create_cart(
            db_session, CartOwnerType.USER, sample_user.id
        )

        # Find the item with the matching SKU
        matching_items = [
            i for i in merged_cart.items if i.product_sku == sample_product.sku
        ]
        assert len(matching_items) == 1, "duplicate SKUs should be merged into one item"
        assert matching_items[0].quantity == 4, (
            "quantities should be summed: 1 + 3 = 4"
        )

    @pytest.mark.asyncio
    async def test_merge_empty_guest_cart_is_no_op(
        self, db_session, sample_user
    ):
        # No guest cart exists for this session ID
        await merge_guest_cart_to_user(
            db_session, "nonexistent-guest-session-01234", sample_user.id
        )
        # Should not raise, just a no-op
