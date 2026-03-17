from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check():
    return {"ok": True, "data": {"status": "healthy"}, "request_id": None}
