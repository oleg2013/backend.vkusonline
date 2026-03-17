from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import redis.asyncio as aioredis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.models.idempotency import IdempotencyKey


async def check_idempotency_redis(
    redis: aioredis.Redis,
    key: str,
    ttl_hours: int = 24,
) -> dict | None:
    cached = await redis.get(f"idempotency:{key}")
    if cached:
        return json.loads(cached)
    return None


async def store_idempotency_redis(
    redis: aioredis.Redis,
    key: str,
    response_data: dict,
    ttl_hours: int = 24,
) -> None:
    await redis.setex(
        f"idempotency:{key}",
        timedelta(hours=ttl_hours),
        json.dumps(response_data, default=str),
    )


async def check_idempotency_db(
    db: AsyncSession,
    key: str,
) -> IdempotencyKey | None:
    stmt = select(IdempotencyKey).where(
        IdempotencyKey.key == key,
        IdempotencyKey.expires_at > datetime.now(UTC),
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def store_idempotency_db(
    db: AsyncSession,
    key: str,
    resource_type: str,
    resource_id: str,
    response_code: int,
    response_body: dict,
    ttl_hours: int = 24,
) -> IdempotencyKey:
    now = datetime.now(UTC)
    record = IdempotencyKey(
        key=key,
        resource_type=resource_type,
        resource_id=resource_id,
        response_code=response_code,
        response_body=response_body,
        created_at=now,
        expires_at=now + timedelta(hours=ttl_hours),
    )
    db.add(record)
    await db.flush()
    return record
