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

    # Subscribe event handlers (same as API process) so that
    # status changes triggered by the poller can send emails.
    from packages.services.events import event_dispatcher
    from packages.services.events.order_handlers import (
        on_order_status_changed,
        on_order_created,
        on_client_event,
    )
    event_dispatcher.subscribe("order_status_changed", on_order_status_changed)
    event_dispatcher.subscribe("order_created", on_order_created)
    event_dispatcher.subscribe("client_event", on_client_event)

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
