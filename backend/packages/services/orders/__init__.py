from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from packages.core.exceptions import ForbiddenError, NotFoundError
from packages.models.order import Order
from packages.models.user import User


async def _get_user_email(db: AsyncSession, user_id: str) -> str | None:
    result = await db.execute(select(User.email).where(User.id == user_id))
    return result.scalar_one_or_none()


def _user_orders_filter(user_id: str, email: str | None):
    """Match orders by user_id OR customer_email (for pre-registration orders)."""
    if email:
        return or_(Order.user_id == user_id, Order.customer_email == email)
    return Order.user_id == user_id


async def _link_orphan_orders(db: AsyncSession, user_id: str, email: str) -> None:
    """Set user_id on orders that match by email but have no user_id."""
    stmt = (
        select(Order)
        .where(Order.customer_email == email, Order.user_id.is_(None))
    )
    result = await db.execute(stmt)
    for order in result.scalars().all():
        order.user_id = user_id
    await db.flush()


async def get_user_orders(
    db: AsyncSession,
    user_id: str,
    page: int = 1,
    per_page: int = 20,
) -> tuple[list[Order], int]:
    email = await _get_user_email(db, user_id)

    # Link orphan orders on first access
    if email:
        await _link_orphan_orders(db, user_id, email)

    where = _user_orders_filter(user_id, email)

    count_stmt = select(Order).where(where)
    count_result = await db.execute(count_stmt)
    total = len(count_result.scalars().all())

    stmt = (
        select(Order)
        .where(where)
        .options(selectinload(Order.items))
        .order_by(Order.created_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    result = await db.execute(stmt)
    orders = list(result.scalars().all())
    return orders, total


async def get_guest_order(
    db: AsyncSession,
    order_number: str,
    guest_session_id: str,
    guest_order_token: str | None = None,
) -> Order:
    stmt = (
        select(Order)
        .where(Order.order_number == order_number, Order.guest_session_id == guest_session_id)
        .options(selectinload(Order.items), selectinload(Order.events))
    )
    result = await db.execute(stmt)
    order = result.scalar_one_or_none()

    if not order:
        raise NotFoundError("Order", order_number)

    return order


async def get_order_by_public_token(
    db: AsyncSession,
    token: str,
) -> Order | None:
    """Fetch order by public token (guest_order_token). Returns None if not found."""
    stmt = (
        select(Order)
        .where(Order.guest_order_token == token)
        .options(selectinload(Order.items), selectinload(Order.events))
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def get_user_order(
    db: AsyncSession,
    order_number: str,
    user_id: str,
) -> Order:
    email = await _get_user_email(db, user_id)
    where = _user_orders_filter(user_id, email)
    stmt = (
        select(Order)
        .where(Order.order_number == order_number, where)
        .options(selectinload(Order.items), selectinload(Order.events))
    )
    result = await db.execute(stmt)
    order = result.scalar_one_or_none()

    if not order:
        raise NotFoundError("Order", order_number)

    return order
