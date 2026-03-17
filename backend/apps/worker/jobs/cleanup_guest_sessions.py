from __future__ import annotations

from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import delete

from packages.core.config import settings
from packages.core.db import async_session_factory
from packages.models.guest import GuestSession

logger = structlog.get_logger(__name__)


async def cleanup_guest_sessions() -> None:
    logger.info("cleanup_guest_sessions_started")
    try:
        cutoff = datetime.now(UTC) - timedelta(days=settings.guest_session_ttl_days)

        async with async_session_factory() as db:
            result = await db.execute(
                delete(GuestSession).where(GuestSession.last_seen_at < cutoff)
            )
            await db.commit()
            deleted = result.rowcount

        logger.info("cleanup_guest_sessions_completed", deleted=deleted)
    except Exception as e:
        logger.exception("cleanup_guest_sessions_failed", error=str(e))
