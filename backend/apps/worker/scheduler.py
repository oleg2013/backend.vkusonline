from __future__ import annotations

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from apps.worker.jobs.cancel_unpaid_orders import cancel_unpaid_orders
from apps.worker.jobs.cleanup_guest_sessions import cleanup_guest_sessions
from apps.worker.jobs.cleanup_idempotency import cleanup_idempotency_keys
from apps.worker.jobs.poll_shipment_statuses import poll_fivepost_statuses, poll_magnit_statuses
from apps.worker.jobs.reconcile_pending_payments import reconcile_pending_payments
from apps.worker.jobs.sync_5post_points import sync_fivepost_points
from apps.worker.jobs.send_email import process_email_queue
from apps.worker.jobs.process_shipments import process_shipment_queue
from apps.worker.jobs.cleanup_logs import cleanup_logs
from apps.worker.jobs.sync_magnit_points import sync_magnit_points
from packages.core.config import settings

logger = structlog.get_logger(__name__)

scheduler = AsyncIOScheduler()


def setup_scheduler() -> AsyncIOScheduler:
    # Sync pickup points caches daily at 6:30 AM
    scheduler.add_job(
        sync_fivepost_points,
        CronTrigger(hour=6, minute=30),
        id="sync_5post_points",
        name="Sync 5Post pickup points",
        replace_existing=True,
    )

    scheduler.add_job(
        sync_magnit_points,
        CronTrigger(hour=7, minute=0),
        id="sync_magnit_points",
        name="Sync Magnit pickup points",
        replace_existing=True,
    )

    # Poll 5Post shipment statuses (configurable interval)
    scheduler.add_job(
        poll_fivepost_statuses,
        IntervalTrigger(minutes=settings.fivepost_poll_interval_minutes),
        id="poll_fivepost_statuses",
        name="Poll 5Post shipment statuses",
        replace_existing=True,
    )

    # Poll Magnit shipment statuses (configurable interval)
    scheduler.add_job(
        poll_magnit_statuses,
        IntervalTrigger(minutes=settings.magnit_poll_interval_minutes),
        id="poll_magnit_statuses",
        name="Poll Magnit shipment statuses",
        replace_existing=True,
    )

    # Reconcile pending payments every 30 minutes
    scheduler.add_job(
        reconcile_pending_payments,
        IntervalTrigger(minutes=30),
        id="reconcile_pending_payments",
        name="Reconcile pending payments",
        replace_existing=True,
    )

    # Cleanup expired guest sessions daily at 3 AM
    scheduler.add_job(
        cleanup_guest_sessions,
        CronTrigger(hour=3, minute=0),
        id="cleanup_guest_sessions",
        name="Cleanup expired guest sessions",
        replace_existing=True,
    )

    # Cleanup expired idempotency keys daily at 4 AM
    scheduler.add_job(
        cleanup_idempotency_keys,
        CronTrigger(hour=4, minute=0),
        id="cleanup_idempotency",
        name="Cleanup expired idempotency keys",
        replace_existing=True,
    )

    # Auto-cancel unpaid PREPAID orders every 10 minutes
    scheduler.add_job(
        cancel_unpaid_orders,
        IntervalTrigger(minutes=10),
        id="cancel_unpaid_orders",
        name="Cancel unpaid orders after timeout",
        replace_existing=True,
    )

    # Process email queue every 5 seconds
    scheduler.add_job(
        process_email_queue,
        IntervalTrigger(seconds=5),
        id="process_email_queue",
        name="Process email sending queue",
        replace_existing=True,
    )

    # Process shipment queue every 10 seconds
    scheduler.add_job(
        process_shipment_queue,
        IntervalTrigger(seconds=10),
        id="process_shipment_queue",
        name="Process shipment creation queue",
        replace_existing=True,
    )

    # Cleanup logs daily at 2 AM
    scheduler.add_job(
        cleanup_logs,
        CronTrigger(hour=2, minute=0),
        id="cleanup_logs",
        name="Cleanup and rotate log files",
        replace_existing=True,
    )

    logger.info("scheduler_configured", jobs=len(scheduler.get_jobs()))
    return scheduler
