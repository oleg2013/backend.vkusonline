from __future__ import annotations

from datetime import UTC, datetime

import structlog

from packages.core.db import async_session_factory
from packages.integrations.price_ftp.client import fetch_latest_price_xml
from packages.integrations.price_ftp.parser import parse_price_xml
from packages.models.price import PriceImportSession
from packages.services.prices import sync_prices_from_xml

logger = structlog.get_logger("worker.sync_prices")


async def sync_prices() -> None:
    logger.info("sync_prices_started")
    async with async_session_factory() as db:
        session = PriceImportSession(status="running")
        db.add(session)
        await db.flush()

        try:
            result = await fetch_latest_price_xml()
            if not result:
                session.status = "failed"
                session.error_message = "No XML files found on FTP"
                session.finished_at = datetime.now(UTC)
                await db.commit()
                logger.warning("sync_prices_no_files")
                return

            xml_content, filename = result
            session.file_name = filename

            parsed = parse_price_xml(xml_content)
            await sync_prices_from_xml(db, parsed, session)

            logger.info("sync_prices_completed", file=filename,
                        matched=session.matched, updated=session.updated, created=session.created)
        except Exception as exc:
            session.status = "failed"
            session.error_message = str(exc)[:500]
            session.finished_at = datetime.now(UTC)
            await db.commit()
            logger.exception("sync_prices_failed", error=str(exc))
