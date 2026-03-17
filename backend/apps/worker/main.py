from __future__ import annotations

import asyncio

# IMPORTANT: import and configure logging first to monkey-patch structlog.get_logger
from packages.core.logging import setup_logging  # noqa: E402
setup_logging()

import structlog

from apps.worker.scheduler import setup_scheduler

logger = structlog.get_logger(__name__)


async def main():
    logger.info("worker_starting")

    scheduler = setup_scheduler()
    scheduler.start()

    logger.info("worker_started", jobs=len(scheduler.get_jobs()))

    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
        logger.info("worker_stopped")


if __name__ == "__main__":
    asyncio.run(main())
