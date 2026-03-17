"""Worker job: reliable email queue processing with crash recovery and dedup.

Uses Redis Hash (email:msgs) for message storage and Sorted Sets
(email:pending / email:processing) for scheduling. Messages are only
deleted after successful send, preventing loss on crashes.
"""

from __future__ import annotations

import json
import time
import uuid

import structlog

from packages.core.redis import get_redis
from packages.services.email import send_email

logger = structlog.get_logger(__name__)

MAX_RETRIES = 5
PROCESSING_LEASE_SECONDS = 60  # how long a message can be "in flight"
BATCH_SIZE = 10
DEDUP_TTL_SECONDS = 86400  # 24h dedup window


async def _migrate_old_queue() -> None:
    """One-time migration: drain old list-based email:queue into new structure."""
    redis = await get_redis()
    migrated = 0
    while True:
        old = await redis.lpop("email:queue")
        if not old:
            break
        try:
            data = json.loads(old)
            msg_id = str(uuid.uuid4())
            data["msg_id"] = msg_id
            data.setdefault("_retries", 0)
            data.setdefault("_created_at", time.time())
            await redis.hset("email:msgs", msg_id, json.dumps(data))
            await redis.zadd("email:pending", {msg_id: time.time()})
            migrated += 1
        except Exception as exc:
            logger.error("email_migration_error", error=str(exc), raw=str(old)[:200])
    if migrated:
        logger.info("email_migrated_from_old_queue", count=migrated)


async def _reclaim_stale(redis, now: float) -> None:
    """Step 1: Reclaim messages stuck in processing (worker crashed mid-send)."""
    stale = await redis.zrangebyscore("email:processing", "-inf", now)
    for msg_id in stale:
        raw = await redis.hget("email:msgs", msg_id)
        if not raw:
            # Message payload gone — just clean up the sorted set entry
            await redis.zrem("email:processing", msg_id)
            continue

        data = json.loads(raw)
        retries = data.get("_retries", 0) + 1

        if retries > MAX_RETRIES:
            # Move to dead letter for admin inspection
            await redis.hset("email:dead", msg_id, raw)
            await redis.zrem("email:processing", msg_id)
            await redis.hdel("email:msgs", msg_id)
            logger.error(
                "email_dead_letter",
                msg_id=msg_id,
                to=data.get("to"),
                subject=data.get("subject"),
                retries=retries,
            )
        else:
            # Put back into pending for retry
            data["_retries"] = retries
            await redis.hset("email:msgs", msg_id, json.dumps(data))
            await redis.zrem("email:processing", msg_id)
            await redis.zadd("email:pending", {msg_id: now})
            logger.warning("email_reclaimed", msg_id=msg_id, retries=retries)


async def _pick_and_send(redis, now: float) -> int:
    """Step 2+3: Pick up ready messages and send them. Returns count processed."""
    ready = await redis.zrangebyscore("email:pending", "-inf", now, start=0, num=BATCH_SIZE)
    processed = 0

    for msg_id in ready:
        # Atomic remove — only one worker/tick can grab this message
        removed = await redis.zrem("email:pending", msg_id)
        if not removed:
            continue  # another tick grabbed it

        # Lease: mark as processing with a deadline
        await redis.zadd("email:processing", {msg_id: now + PROCESSING_LEASE_SECONDS})

        raw = await redis.hget("email:msgs", msg_id)
        if not raw:
            await redis.zrem("email:processing", msg_id)
            continue

        # Dedup: already sent?
        if await redis.exists(f"email:sent:{msg_id}"):
            await redis.zrem("email:processing", msg_id)
            await redis.hdel("email:msgs", msg_id)
            logger.info("email_dedup_skipped", msg_id=msg_id)
            processed += 1
            continue

        data = json.loads(raw)
        success = await send_email(
            data["to"], data["subject"], data["body"], data.get("from_addr")
        )

        if success:
            # Mark as sent (dedup marker), clean up
            await redis.setex(f"email:sent:{msg_id}", DEDUP_TTL_SECONDS, "1")
            await redis.zrem("email:processing", msg_id)
            await redis.hdel("email:msgs", msg_id)
        else:
            # Leave in processing — _reclaim_stale will handle retry on next cycle
            # But increment retry counter now so we don't wait for lease expiry
            retries = data.get("_retries", 0) + 1
            if retries > MAX_RETRIES:
                await redis.hset("email:dead", msg_id, raw)
                await redis.zrem("email:processing", msg_id)
                await redis.hdel("email:msgs", msg_id)
                logger.error(
                    "email_dead_letter",
                    msg_id=msg_id,
                    to=data.get("to"),
                    subject=data.get("subject"),
                    retries=retries,
                )
            else:
                data["_retries"] = retries
                await redis.hset("email:msgs", msg_id, json.dumps(data))
                await redis.zrem("email:processing", msg_id)
                await redis.zadd("email:pending", {msg_id: now + 10 * retries})  # backoff
                logger.warning(
                    "email_retry_queued",
                    msg_id=msg_id,
                    to=data.get("to"),
                    retries=retries,
                )

        processed += 1

    return processed


async def process_email_queue() -> None:
    """Main entry point. Called by APScheduler every 5 seconds."""
    redis = await get_redis()
    now = time.time()

    # One-time migration of old list-based queue
    await _migrate_old_queue()

    # Step 1: Reclaim stale messages from crashed workers
    await _reclaim_stale(redis, now)

    # Step 2+3: Pick up and send
    processed = await _pick_and_send(redis, now)

    if processed:
        logger.info("email_queue_processed", count=processed)
