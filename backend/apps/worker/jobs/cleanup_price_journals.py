from __future__ import annotations

import structlog

from packages.core.config import settings
from packages.core.db import async_session_factory
from packages.services.prices import cleanup_old_sessions

logger = structlog.get_logger("worker.cleanup_price_journals")


async def cleanup_price_journals() -> None:
    logger.info("cleanup_price_journals_started")
    async with async_session_factory() as db:
        deleted = await cleanup_old_sessions(db, settings.price_import_journal_retention_days)
        logger.info("cleanup_price_journals_done", deleted=deleted)
