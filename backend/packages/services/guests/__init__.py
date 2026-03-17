from __future__ import annotations

from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.core.config import settings
from packages.core.exceptions import AuthError
from packages.models.guest import GuestSession

logger = structlog.get_logger(__name__)


async def ensure_guest_session(
    db: AsyncSession,
    guest_session_id: str,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> tuple[GuestSession, bool]:
    if not guest_session_id or len(guest_session_id) < 10:
        raise AuthError("Invalid guest session ID")

    stmt = select(GuestSession).where(GuestSession.id == guest_session_id)
    result = await db.execute(stmt)
    session = result.scalar_one_or_none()

    if session:
        if session.merged_to_user_id:
            raise AuthError("This guest session has been merged to a user account")

        session.last_seen_at = datetime.now(UTC)
        if ip_address:
            session.ip_address = ip_address
        await db.flush()
        return session, False

    session = GuestSession(
        id=guest_session_id,
        last_seen_at=datetime.now(UTC),
        ip_address=ip_address,
        user_agent=user_agent,
    )
    db.add(session)
    await db.flush()
    logger.info("guest_session_created", guest_session_id=guest_session_id)
    return session, True


async def validate_guest_session(
    db: AsyncSession,
    guest_session_id: str,
) -> GuestSession:
    stmt = select(GuestSession).where(GuestSession.id == guest_session_id)
    result = await db.execute(stmt)
    session = result.scalar_one_or_none()

    if not session:
        raise AuthError("Guest session not found")

    if session.merged_to_user_id:
        raise AuthError("Guest session has been merged")

    ttl = timedelta(days=settings.guest_session_ttl_days)
    if datetime.now(UTC) - session.last_seen_at > ttl:
        raise AuthError("Guest session expired")

    session.last_seen_at = datetime.now(UTC)
    await db.flush()
    return session


async def merge_guest_to_user(
    db: AsyncSession,
    guest_session_id: str,
    user_id: str,
) -> None:
    session = await validate_guest_session(db, guest_session_id)
    session.merged_to_user_id = user_id
    await db.flush()
    logger.info("guest_session_merged", guest_session_id=guest_session_id, user_id=user_id)
