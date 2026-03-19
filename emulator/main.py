"""Delivery API Emulator — 5Post & Magnit.

A single FastAPI application that emulates both 5Post and Magnit delivery
provider APIs for order lifecycle testing.

Run with:  python -m uvicorn main:app --host 0.0.0.0 --port 8001
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from config import settings
from database import init_db
from routers import admin, fivepost, magnit


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create emulator tables on startup."""
    logging.basicConfig(level=getattr(logging, settings.log_level, logging.INFO))
    logging.getLogger("emulator").info("Initializing emulator database tables...")
    await init_db()
    logging.getLogger("emulator").info("Emulator ready.")
    yield


app = FastAPI(
    title="Delivery API Emulator (5Post & Magnit)",
    description="Emulates order creation and status tracking for 5Post and Magnit delivery providers.",
    version="1.0.0",
    lifespan=lifespan,
)

# Mount both providers' routes at root — no prefix overlap between them.
app.include_router(fivepost.router, tags=["5Post"])
app.include_router(magnit.router, tags=["Magnit"])
app.include_router(admin.router)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "delivery-emulator"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=True,
    )
