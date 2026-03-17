from __future__ import annotations

from datetime import UTC, datetime

import structlog
from sqlalchemy import delete

from packages.core.db import async_session_factory
from packages.models.idempotency import IdempotencyKey

logger = structlog.get_logger(__name__)


async def cleanup_idempotency_keys() -> None:
    logger.info("cleanup_idempotency_started")
    try:
        async with async_session_factory() as db:
            result = await db.execute(
                delete(IdempotencyKey).where(IdempotencyKey.expires_at < datetime.now(UTC))
            )
            await db.commit()
            deleted = result.rowcount

        logger.info("cleanup_idempotency_completed", deleted=deleted)
    except Exception as e:
        logger.exception("cleanup_idempotency_failed", error=str(e))
