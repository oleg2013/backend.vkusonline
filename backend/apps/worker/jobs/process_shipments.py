"""Worker job: reliable shipment queue processing with crash recovery and retry.

Uses Redis Hash (shipment:msgs) for task storage and Sorted Sets
(shipment:pending / shipment:processing) for scheduling.
Shipment tasks are only deleted after successful creation at the provider,
preventing loss on crashes or transient API failures.

Queue keys:
  - shipment:msgs        Hash: msg_id → JSON payload
  - shipment:pending     Sorted Set: msg_id → scheduled timestamp
  - shipment:processing  Sorted Set: msg_id → lease deadline
  - shipment:done:{id}   String with TTL: dedup marker
  - shipment:dead        Hash: msg_id → JSON payload (permanently failed)
"""

from __future__ import annotations

import json
import time

import structlog

from packages.core.redis import get_redis

logger = structlog.get_logger("worker.shipments")

MAX_RETRIES = 5
PROCESSING_LEASE_SECONDS = 120  # 2 min — provider APIs can be slow
BATCH_SIZE = 5
DEDUP_TTL_SECONDS = 86400 * 7  # 7 days dedup window


async def enqueue_shipment(order_id: str, order_number: str) -> str:
    """Add a shipment creation task to the reliable queue.

    Called from event handler when order transitions to SHIPPED.
    Returns the msg_id for tracking.
    """
    import uuid

    redis = await get_redis()
    msg_id = str(uuid.uuid4())

    # Dedup: don't queue if already successfully created
    if await redis.exists(f"shipment:done:{order_id}"):
        logger.info("shipment_enqueue_dedup", order_id=order_id, order_number=order_number)
        return msg_id

    payload = json.dumps({
        "msg_id": msg_id,
        "order_id": order_id,
        "order_number": order_number,
        "_retries": 0,
        "_created_at": time.time(),
    })
    await redis.hset("shipment:msgs", msg_id, payload)
    await redis.zadd("shipment:pending", {msg_id: time.time()})
    logger.info("shipment_enqueued", msg_id=msg_id, order_number=order_number)
    return msg_id


async def _reclaim_stale(redis, now: float) -> None:
    """Reclaim tasks stuck in processing (worker crashed mid-call)."""
    stale = await redis.zrangebyscore("shipment:processing", "-inf", now)
    for msg_id in stale:
        raw = await redis.hget("shipment:msgs", msg_id)
        if not raw:
            await redis.zrem("shipment:processing", msg_id)
            continue

        data = json.loads(raw)
        retries = data.get("_retries", 0) + 1

        if retries > MAX_RETRIES:
            await redis.hset("shipment:dead", msg_id, raw)
            await redis.zrem("shipment:processing", msg_id)
            await redis.hdel("shipment:msgs", msg_id)
            logger.error(
                "shipment_dead_letter",
                msg_id=msg_id,
                order_number=data.get("order_number"),
                retries=retries,
            )
        else:
            data["_retries"] = retries
            await redis.hset("shipment:msgs", msg_id, json.dumps(data))
            await redis.zrem("shipment:processing", msg_id)
            # Exponential backoff: 30s, 60s, 120s, 240s, 480s
            backoff = 30 * (2 ** (retries - 1))
            await redis.zadd("shipment:pending", {msg_id: now + backoff})
            logger.warning("shipment_reclaimed", msg_id=msg_id, order_number=data.get("order_number"), retries=retries, next_in=backoff)


async def _create_shipment_for_order(order_id: str) -> str | None:
    """Load order from DB and create shipment at provider. Returns provider_shipment_id or None."""
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from packages.core.db import async_session_factory
    from packages.models.order import Order
    from packages.models.shipment import Shipment
    from packages.services.shipments import create_shipment

    async with async_session_factory() as db:
        # Check if shipment already exists
        existing = await db.execute(
            select(Shipment).where(Shipment.order_id == order_id)
        )
        if existing.scalar_one_or_none():
            logger.info("shipment_already_exists", order_id=order_id)
            return "already_exists"

        # Load order with items
        stmt = select(Order).where(Order.id == order_id).options(selectinload(Order.items))
        result = await db.execute(stmt)
        order = result.scalar_one_or_none()
        if not order:
            logger.error("shipment_order_not_found", order_id=order_id)
            return None

        shipment = await create_shipment(db, order)
        await db.commit()
        return shipment.provider_shipment_id


async def _pick_and_process(redis, now: float) -> int:
    """Pick up ready tasks and create shipments. Returns count processed."""
    ready = await redis.zrangebyscore("shipment:pending", "-inf", now, start=0, num=BATCH_SIZE)
    processed = 0

    for msg_id in ready:
        removed = await redis.zrem("shipment:pending", msg_id)
        if not removed:
            continue

        await redis.zadd("shipment:processing", {msg_id: now + PROCESSING_LEASE_SECONDS})

        raw = await redis.hget("shipment:msgs", msg_id)
        if not raw:
            await redis.zrem("shipment:processing", msg_id)
            continue

        data = json.loads(raw)
        order_id = data["order_id"]
        order_number = data.get("order_number", "?")

        # Dedup
        if await redis.exists(f"shipment:done:{order_id}"):
            await redis.zrem("shipment:processing", msg_id)
            await redis.hdel("shipment:msgs", msg_id)
            logger.info("shipment_dedup_skipped", msg_id=msg_id, order_number=order_number)
            processed += 1
            continue

        try:
            provider_id = await _create_shipment_for_order(order_id)

            if provider_id:
                # Success — mark done
                await redis.setex(f"shipment:done:{order_id}", DEDUP_TTL_SECONDS, provider_id)
                await redis.zrem("shipment:processing", msg_id)
                await redis.hdel("shipment:msgs", msg_id)
                logger.info("shipment_created", order_number=order_number, provider_id=provider_id)
            else:
                raise RuntimeError("create_shipment returned None")

        except Exception as exc:
            retries = data.get("_retries", 0) + 1
            if retries > MAX_RETRIES:
                await redis.hset("shipment:dead", msg_id, raw)
                await redis.zrem("shipment:processing", msg_id)
                await redis.hdel("shipment:msgs", msg_id)
                logger.error("shipment_dead_letter", msg_id=msg_id, order_number=order_number, error=str(exc), retries=retries)
            else:
                data["_retries"] = retries
                data["_last_error"] = str(exc)
                await redis.hset("shipment:msgs", msg_id, json.dumps(data))
                await redis.zrem("shipment:processing", msg_id)
                backoff = 30 * (2 ** (retries - 1))
                await redis.zadd("shipment:pending", {msg_id: now + backoff})
                logger.warning("shipment_retry_queued", msg_id=msg_id, order_number=order_number, error=str(exc), retries=retries, next_in=backoff)

        processed += 1

    return processed


async def process_shipment_queue() -> None:
    """Main entry point. Called by APScheduler every 10 seconds."""
    redis = await get_redis()
    now = time.time()

    await _reclaim_stale(redis, now)
    processed = await _pick_and_process(redis, now)

    if processed:
        logger.info("shipment_queue_processed", count=processed)
