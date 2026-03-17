from __future__ import annotations

import redis.asyncio as aioredis

from packages.core.exceptions import RateLimitError


async def check_rate_limit(
    redis: aioredis.Redis,
    key: str,
    max_requests: int,
    window_seconds: int,
) -> None:
    full_key = f"ratelimit:{key}"
    current = await redis.incr(full_key)
    if current == 1:
        await redis.expire(full_key, window_seconds)
    if current > max_requests:
        ttl = await redis.ttl(full_key)
        raise RateLimitError(
            f"Rate limit exceeded. Try again in {ttl} seconds."
        )
