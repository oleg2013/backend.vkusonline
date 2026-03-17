from __future__ import annotations

import redis.asyncio as aioredis

from packages.core.config import settings

redis_client: aioredis.Redis = aioredis.from_url(
    settings.redis_url,
    decode_responses=True,
    max_connections=20,
)


async def get_redis() -> aioredis.Redis:
    return redis_client


async def close_redis() -> None:
    await redis_client.aclose()
