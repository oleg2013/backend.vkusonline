"""Shared pytest fixtures for the VKUS ONLINE backend test suite."""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from packages.models.base import Base

# Import all model modules so that Base.metadata is fully populated.
import packages.models.user  # noqa: F401
import packages.models.guest  # noqa: F401
import packages.models.catalog  # noqa: F401
import packages.models.cart  # noqa: F401
import packages.models.order  # noqa: F401
import packages.models.payment  # noqa: F401
import packages.models.discount  # noqa: F401
import packages.models.idempotency  # noqa: F401
import packages.models.shipment  # noqa: F401
import packages.models.pickup_point  # noqa: F401
import packages.models.provider  # noqa: F401
import packages.models.address  # noqa: F401

# ---------------------------------------------------------------------------
# SQLite compatibility: map PostgreSQL JSONB -> generic JSON for tests
# ---------------------------------------------------------------------------
# This allows all models that declare JSONB columns to work with SQLite.
# We compile JSONB as JSON when the dialect is SQLite.
from sqlalchemy.ext.compiler import compiles

@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(element, compiler, **kw):
    return "JSON"


# ---------------------------------------------------------------------------
# Database fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Create an in-memory SQLite async session with all tables."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
        json_serializer=json.dumps,
        json_deserializer=json.loads,
    )

    # Create tables using a synchronous connection (run_sync).
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with session_factory() as session:
        yield session
        await session.rollback()

    await engine.dispose()


# ---------------------------------------------------------------------------
# Redis mock
# ---------------------------------------------------------------------------

class _RedisMock:
    """Minimal async Redis mock implementing get/set/incr/expire/ttl/setex/aclose."""

    def __init__(self) -> None:
        self._store: dict[str, Any] = {}
        self._ttls: dict[str, float] = {}

    async def get(self, key: str) -> Any:
        return self._store.get(key)

    async def set(self, key: str, value: Any, **kwargs: Any) -> None:
        self._store[key] = value

    async def setex(self, key: str, time: int | timedelta, value: Any) -> None:
        self._store[key] = value
        if isinstance(time, timedelta):
            seconds = time.total_seconds()
        else:
            seconds = time
        self._ttls[key] = seconds

    async def incr(self, key: str) -> int:
        current = self._store.get(key, 0)
        if isinstance(current, str) and current.isdigit():
            current = int(current)
        new_val = int(current) + 1
        self._store[key] = new_val
        return new_val

    async def expire(self, key: str, time: int) -> None:
        self._ttls[key] = time

    async def ttl(self, key: str) -> int:
        if key not in self._ttls:
            return -1
        return int(self._ttls[key])

    async def delete(self, *keys: str) -> None:
        for key in keys:
            self._store.pop(key, None)
            self._ttls.pop(key, None)

    async def aclose(self) -> None:
        self._store.clear()
        self._ttls.clear()


@pytest.fixture
def redis_mock() -> _RedisMock:
    """Return a simple in-memory Redis mock."""
    return _RedisMock()


# ---------------------------------------------------------------------------
# FastAPI test client
# ---------------------------------------------------------------------------

@pytest.fixture
async def async_client(db_session: AsyncSession, redis_mock: _RedisMock) -> AsyncGenerator[AsyncClient, None]:
    """Create an httpx.AsyncClient wired to the FastAPI app with overridden deps."""
    from apps.api.main import app
    from packages.core.db import get_db
    from packages.core.redis import get_redis

    async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    async def _override_get_redis():
        return redis_mock

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_redis] = _override_get_redis

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Domain object fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
async def sample_user(db_session: AsyncSession):
    """Create and return a test user in the database."""
    from packages.core.security import hash_password
    from packages.models.user import User, UserProfile

    user = User(
        email="test@example.com",
        phone="+79991234567",
        password_hash=hash_password("TestPass123"),
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()

    profile = UserProfile(
        user_id=user.id,
        first_name="Test",
        last_name="User",
        display_name="Test User",
    )
    db_session.add(profile)
    await db_session.flush()

    return user


@pytest.fixture
async def sample_guest_session(db_session: AsyncSession):
    """Create and return a test guest session in the database."""
    from packages.models.guest import GuestSession

    session = GuestSession(
        id="test-guest-session-id-1234567890",
        last_seen_at=datetime.now(UTC),
        ip_address="127.0.0.1",
        user_agent="pytest",
    )
    db_session.add(session)
    await db_session.flush()
    return session


@pytest.fixture
async def sample_product(db_session: AsyncSession):
    """Create and return a test product with its product family."""
    from packages.models.catalog import Product, ProductFamily

    family = ProductFamily(
        slug="premium-tea",
        name="Premium Tea Collection",
        category="tea",
        subcategory="black",
        description="Fine black tea",
        is_active=True,
    )
    db_session.add(family)
    await db_session.flush()

    product = Product(
        sku="TEA-BLK-001",
        family_id=family.id,
        name="Earl Grey Premium 100g",
        variant_label="100g",
        price=45000,  # 450.00 RUB in kopecks
        weight_grams=120,
        vat_rate=20,
        is_active=True,
        sort_order=1,
    )
    db_session.add(product)
    await db_session.flush()

    return product


@pytest.fixture
async def sample_cart(db_session: AsyncSession, sample_product):
    """Create a cart with one item for a guest session."""
    from packages.models.cart import Cart, CartItem

    cart = Cart(
        owner_type="guest",
        guest_session_id="test-guest-session-id-1234567890",
    )
    db_session.add(cart)
    await db_session.flush()

    item = CartItem(
        cart_id=cart.id,
        product_sku=sample_product.sku,
        quantity=2,
        price_snapshot=sample_product.price,
    )
    db_session.add(item)
    await db_session.flush()

    cart.items = [item]
    return cart
