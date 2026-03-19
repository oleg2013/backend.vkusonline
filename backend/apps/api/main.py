from __future__ import annotations

# IMPORTANT: configure logging FIRST — before any module imports structlog
from packages.core.logging import setup_logging  # noqa: E402, I001
setup_logging()

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import ORJSONResponse

from apps.api.middleware.error_handler import register_exception_handlers
from apps.api.middleware.request_id import RequestIdMiddleware
from packages.core.log_middleware import RequestLogMiddleware
from apps.api.routers import (
    admin,
    auth,
    bootstrap,
    cart,
    catalog,
    checkout,
    delivery_5post,
    delivery_magnit,
    geo,
    guest,
    health,
    me,
    orders,
    payments,
    public_orders,
    webhooks,
)
from packages.core.config import settings
from packages.core.db import dispose_engine
from packages.core.redis import close_redis


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Register event handlers
    from packages.services.events import event_dispatcher
    from packages.services.events.order_handlers import (
        on_client_event,
        on_order_created,
        on_order_status_changed,
    )
    event_dispatcher.subscribe("order_status_changed", on_order_status_changed)
    event_dispatcher.subscribe("order_created", on_order_created)
    event_dispatcher.subscribe("client_event", on_client_event)
    yield
    await close_redis()
    await dispose_engine()


app = FastAPI(
    title="VKUS ONLINE API",
    version="0.1.0",
    default_response_class=ORJSONResponse,
    lifespan=lifespan,
    docs_url="/api/docs" if settings.app_debug else None,
    redoc_url="/api/redoc" if settings.app_debug else None,
)

# Exception handlers (replaces ErrorHandlerMiddleware to preserve async context)
register_exception_handlers(app)

# Middleware (order matters: outermost first)
app.add_middleware(RequestLogMiddleware)
app.add_middleware(RequestIdMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
)

# Routers
PREFIX = "/api/v1"
app.include_router(health.router, prefix=PREFIX)
app.include_router(bootstrap.router, prefix=PREFIX)
app.include_router(auth.router, prefix=PREFIX)
app.include_router(guest.router, prefix=PREFIX)
app.include_router(catalog.router, prefix=PREFIX)
app.include_router(geo.router, prefix=PREFIX)
app.include_router(cart.router, prefix=PREFIX)
app.include_router(checkout.router, prefix=PREFIX)
app.include_router(orders.router, prefix=PREFIX)
app.include_router(payments.router, prefix=PREFIX)
app.include_router(delivery_5post.router, prefix=PREFIX)
app.include_router(delivery_magnit.router, prefix=PREFIX)
app.include_router(me.router, prefix=PREFIX)
app.include_router(webhooks.router, prefix=PREFIX)
app.include_router(public_orders.router, prefix=PREFIX)
app.include_router(admin.router, prefix=PREFIX)


@app.get("/api/v1/delivery/options")
async def delivery_options():
    return {
        "ok": True,
        "data": [
            {
                "provider": "5post",
                "name": "5Post",
                "description": "Доставка в постаматы и пункты выдачи 5Post",
                "available": True,
            },
            {
                "provider": "magnit",
                "name": "Магнит Пост",
                "description": "Доставка в магазины Магнит",
                "available": True,
            },
        ],
        "request_id": None,
    }
