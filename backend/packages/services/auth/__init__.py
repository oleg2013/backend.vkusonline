from __future__ import annotations

from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.core.config import settings
from packages.core.exceptions import AuthError, ConflictError, ValidationError
from packages.core.security import (
    create_access_token,
    create_refresh_token,
    hash_password,
    hash_token,
    verify_password,
)
from packages.core.utils import validate_email, validate_phone
from packages.models.user import RefreshToken, User, UserProfile

logger = structlog.get_logger(__name__)


async def register_user(
    db: AsyncSession,
    email: str,
    password: str,
    phone: str | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
) -> tuple[User, str, str]:
    if not validate_email(email):
        raise ValidationError("Invalid email format")
    if len(password) < 8:
        raise ValidationError("Password must be at least 8 characters")

    existing = await db.execute(select(User).where(User.email == email))
    if existing.scalar_one_or_none():
        raise ConflictError("User with this email already exists")

    if phone:
        normalized = validate_phone(phone)
        if not normalized:
            raise ValidationError("Invalid phone format")
        phone = normalized

    user = User(
        email=email.lower().strip(),
        phone=phone,
        password_hash=hash_password(password),
        plain_password=password,
    )
    db.add(user)
    await db.flush()

    profile = UserProfile(
        user_id=user.id,
        first_name=first_name,
        last_name=last_name,
        display_name=f"{first_name or ''} {last_name or ''}".strip() or None,
    )
    db.add(profile)
    await db.flush()

    access_token = create_access_token(user.id)
    refresh_token_raw = create_refresh_token()
    await _store_refresh_token(db, user.id, refresh_token_raw)

    logger.info("user_registered", user_id=user.id, email=email)
    return user, access_token, refresh_token_raw


async def login_user(
    db: AsyncSession,
    email: str,
    password: str,
    user_agent: str | None = None,
    ip_address: str | None = None,
) -> tuple[User, str, str]:
    stmt = select(User).where(User.email == email.lower().strip())
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if not user or not verify_password(password, user.password_hash):
        raise AuthError("Invalid email or password")

    if not user.is_active:
        raise AuthError("Account is deactivated")

    access_token = create_access_token(user.id)
    refresh_token_raw = create_refresh_token()
    await _store_refresh_token(db, user.id, refresh_token_raw, user_agent, ip_address)

    logger.info("user_logged_in", user_id=user.id)
    return user, access_token, refresh_token_raw


async def refresh_tokens(
    db: AsyncSession,
    refresh_token_raw: str,
) -> tuple[str, str]:
    token_hash = hash_token(refresh_token_raw)
    stmt = select(RefreshToken).where(
        RefreshToken.token_hash == token_hash,
        RefreshToken.revoked_at.is_(None),
    )
    result = await db.execute(stmt)
    rt = result.scalar_one_or_none()

    if not rt:
        raise AuthError("Invalid refresh token")

    if rt.expires_at < datetime.now(UTC):
        raise AuthError("Refresh token expired")

    # Rotate: revoke old, create new
    rt.revoked_at = datetime.now(UTC)

    new_access = create_access_token(rt.user_id)
    new_refresh_raw = create_refresh_token()
    await _store_refresh_token(db, rt.user_id, new_refresh_raw, rt.user_agent, rt.ip_address)

    logger.info("tokens_refreshed", user_id=rt.user_id)
    return new_access, new_refresh_raw


async def logout_user(db: AsyncSession, refresh_token_raw: str) -> None:
    token_hash = hash_token(refresh_token_raw)
    stmt = select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    result = await db.execute(stmt)
    rt = result.scalar_one_or_none()
    if rt:
        rt.revoked_at = datetime.now(UTC)
        logger.info("user_logged_out", user_id=rt.user_id)


async def _store_refresh_token(
    db: AsyncSession,
    user_id: str,
    raw_token: str,
    user_agent: str | None = None,
    ip_address: str | None = None,
) -> RefreshToken:
    rt = RefreshToken(
        user_id=user_id,
        token_hash=hash_token(raw_token),
        expires_at=datetime.now(UTC) + timedelta(days=settings.jwt_refresh_token_expire_days),
        user_agent=user_agent,
        ip_address=ip_address,
    )
    db.add(rt)
    await db.flush()
    return rt
