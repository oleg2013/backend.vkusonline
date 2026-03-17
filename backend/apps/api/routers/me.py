from __future__ import annotations

from fastapi import APIRouter

from apps.api.deps import CurrentUserId, DbSession, OptionalGuestSessionId, RequestId
from packages.core.exceptions import NotFoundError
from packages.models.address import Address
from packages.models.user import User, UserProfile
from packages.schemas.user import AddressCreate, AddressUpdate, UserUpdateRequest
from packages.services import cart as cart_service
from packages.services import guests as guest_service
from packages.services import discounts as discounts_service
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

router = APIRouter(prefix="/me", tags=["me"])


@router.get("")
async def get_profile(user_id: CurrentUserId, db: DbSession, request_id: RequestId):
    stmt = select(User).where(User.id == user_id).options(selectinload(User.profile))
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    if not user:
        raise NotFoundError("User", user_id)

    p = user.profile
    return {
        "ok": True,
        "data": {
            "id": user.id,
            "email": user.email,
            "phone": user.phone,
            "first_name": p.first_name if p else None,
            "last_name": p.last_name if p else None,
            "display_name": p.display_name if p else None,
            "created_at": user.created_at.isoformat() if user.created_at else None,
        },
        "request_id": request_id,
    }


@router.patch("")
async def update_profile(
    body: UserUpdateRequest,
    user_id: CurrentUserId,
    db: DbSession,
    request_id: RequestId,
):
    stmt = select(User).where(User.id == user_id).options(selectinload(User.profile))
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    if not user:
        raise NotFoundError("User", user_id)

    if body.phone is not None:
        from packages.core.utils import validate_phone

        normalized = validate_phone(body.phone)
        if not normalized:
            from packages.core.exceptions import ValidationError

            raise ValidationError("Invalid phone format")
        user.phone = normalized

    p = user.profile
    if not p:
        p = UserProfile(user_id=user.id)
        db.add(p)

    if body.first_name is not None:
        p.first_name = body.first_name
    if body.last_name is not None:
        p.last_name = body.last_name

    p.display_name = f"{p.first_name or ''} {p.last_name or ''}".strip() or None
    await db.flush()

    return {
        "ok": True,
        "data": {"message": "Profile updated"},
        "request_id": request_id,
    }


@router.get("/addresses")
async def list_addresses(user_id: CurrentUserId, db: DbSession, request_id: RequestId):
    stmt = select(Address).where(Address.user_id == user_id).order_by(Address.is_default.desc())
    result = await db.execute(stmt)
    addresses = result.scalars().all()
    return {
        "ok": True,
        "data": [
            {
                "id": a.id,
                "label": a.label,
                "city": a.city,
                "street": a.street,
                "house": a.house,
                "apartment": a.apartment,
                "postal_code": a.postal_code,
                "full_address": a.full_address,
                "lat": a.lat,
                "lon": a.lon,
                "is_default": a.is_default,
            }
            for a in addresses
        ],
        "request_id": request_id,
    }


@router.post("/addresses")
async def create_address(
    body: AddressCreate,
    user_id: CurrentUserId,
    db: DbSession,
    request_id: RequestId,
):
    if body.is_default:
        await _unset_default(db, user_id)

    addr = Address(
        user_id=user_id,
        label=body.label,
        city=body.city,
        street=body.street,
        house=body.house,
        apartment=body.apartment,
        postal_code=body.postal_code,
        full_address=body.full_address,
        lat=body.lat,
        lon=body.lon,
        is_default=body.is_default or False,
    )
    db.add(addr)
    await db.flush()
    return {"ok": True, "data": {"id": addr.id}, "request_id": request_id}


@router.patch("/addresses/{address_id}")
async def update_address(
    address_id: str,
    body: AddressUpdate,
    user_id: CurrentUserId,
    db: DbSession,
    request_id: RequestId,
):
    addr = await _get_user_address(db, address_id, user_id)
    update_data = body.model_dump(exclude_unset=True)

    if update_data.get("is_default"):
        await _unset_default(db, user_id)

    for key, value in update_data.items():
        setattr(addr, key, value)
    await db.flush()
    return {"ok": True, "data": {"message": "Address updated"}, "request_id": request_id}


@router.delete("/addresses/{address_id}")
async def delete_address(
    address_id: str,
    user_id: CurrentUserId,
    db: DbSession,
    request_id: RequestId,
):
    addr = await _get_user_address(db, address_id, user_id)
    await db.delete(addr)
    await db.flush()
    return {"ok": True, "data": {"message": "Address deleted"}, "request_id": request_id}


@router.post("/merge-guest-session")
async def merge_guest(
    user_id: CurrentUserId,
    guest_session_id: OptionalGuestSessionId,
    db: DbSession,
    request_id: RequestId,
):
    if not guest_session_id:
        from packages.core.exceptions import ValidationError

        raise ValidationError("X-Guest-Session-ID header required for merge")

    await guest_service.merge_guest_to_user(db, guest_session_id, user_id)
    await cart_service.merge_guest_cart_to_user(db, guest_session_id, user_id)

    return {
        "ok": True,
        "data": {"message": "Guest session merged"},
        "request_id": request_id,
    }


@router.get("/discounts")
async def get_discounts(user_id: CurrentUserId, db: DbSession, request_id: RequestId):
    discounts = await discounts_service.get_customer_discounts(db, user_id)
    return {
        "ok": True,
        "data": [
            {
                "name": d.name,
                "type": d.discount_type,
                "value": d.value,
                "is_active": d.is_active,
            }
            for d in discounts
        ],
        "request_id": request_id,
    }


@router.get("/loyalty-summary")
async def loyalty_summary(user_id: CurrentUserId, db: DbSession, request_id: RequestId):
    # TODO: implement loyalty program
    return {
        "ok": True,
        "data": {"level": "standard", "points": 0, "next_level": None},
        "request_id": request_id,
    }


async def _get_user_address(db: AsyncSession, address_id: str, user_id: str) -> Address:
    stmt = select(Address).where(Address.id == address_id, Address.user_id == user_id)
    result = await db.execute(stmt)
    addr = result.scalar_one_or_none()
    if not addr:
        raise NotFoundError("Address", address_id)
    return addr


async def _unset_default(db: AsyncSession, user_id: str) -> None:
    stmt = select(Address).where(Address.user_id == user_id, Address.is_default.is_(True))
    result = await db.execute(stmt)
    for addr in result.scalars().all():
        addr.is_default = False
