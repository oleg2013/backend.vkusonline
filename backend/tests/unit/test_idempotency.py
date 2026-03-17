"""Unit tests for packages.core.idempotency (Redis-based functions)."""

from __future__ import annotations

import pytest

from packages.core.idempotency import check_idempotency_redis, store_idempotency_redis


class TestIdempotencyRedis:
    """Tests for check_idempotency_redis and store_idempotency_redis."""

    @pytest.mark.asyncio
    async def test_check_returns_none_when_not_set(self, redis_mock):
        result = await check_idempotency_redis(redis_mock, "nonexistent-key")
        assert result is None, "check_idempotency_redis should return None for a missing key"

    @pytest.mark.asyncio
    async def test_store_and_check_returns_stored_data(self, redis_mock):
        key = "order-create-abc123"
        data = {"order_id": "ord-001", "status": "created"}

        await store_idempotency_redis(redis_mock, key, data)
        result = await check_idempotency_redis(redis_mock, key)

        assert result is not None, "check should return data after store"
        assert result["order_id"] == "ord-001", "stored order_id should match"
        assert result["status"] == "created", "stored status should match"

    @pytest.mark.asyncio
    async def test_store_uses_prefixed_key(self, redis_mock):
        key = "my-key"
        await store_idempotency_redis(redis_mock, key, {"ok": True})

        # The actual Redis key should be "idempotency:my-key"
        raw = await redis_mock.get("idempotency:my-key")
        assert raw is not None, "data should be stored under 'idempotency:' prefix"

    @pytest.mark.asyncio
    async def test_store_sets_ttl_via_setex(self, redis_mock):
        key = "ttl-test"
        await store_idempotency_redis(redis_mock, key, {"data": 1}, ttl_hours=48)

        # setex was called, so the TTL dict should have the key
        ttl_val = await redis_mock.ttl("idempotency:ttl-test")
        assert ttl_val > 0, "TTL should be set for the stored key"

    @pytest.mark.asyncio
    async def test_different_keys_are_independent(self, redis_mock):
        await store_idempotency_redis(redis_mock, "key-a", {"id": "a"})
        await store_idempotency_redis(redis_mock, "key-b", {"id": "b"})

        result_a = await check_idempotency_redis(redis_mock, "key-a")
        result_b = await check_idempotency_redis(redis_mock, "key-b")

        assert result_a["id"] == "a"
        assert result_b["id"] == "b"

    @pytest.mark.asyncio
    async def test_overwrite_existing_key(self, redis_mock):
        key = "overwrite-test"
        await store_idempotency_redis(redis_mock, key, {"version": 1})
        await store_idempotency_redis(redis_mock, key, {"version": 2})

        result = await check_idempotency_redis(redis_mock, key)
        assert result["version"] == 2, "second store should overwrite the first"
