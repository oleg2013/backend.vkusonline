from __future__ import annotations

from fastapi import APIRouter, Request

from apps.api.deps import DbSession, Redis, RequestId
from packages.core.rate_limit import check_rate_limit
from packages.schemas.guest import GuestBootstrapRequest, GuestBootstrapResponse
from packages.services import guests as guest_service

router = APIRouter(prefix="/guest", tags=["guest"])


@router.post("/session/bootstrap")
async def bootstrap_guest_session(
    body: GuestBootstrapRequest,
    db: DbSession,
    redis: Redis,
    request: Request,
    request_id: RequestId,
):
    client_ip = request.client.host if request.client else "unknown"
    await check_rate_limit(redis, f"guest_bootstrap:{client_ip}", max_requests=30, window_seconds=60)

    user_agent = request.headers.get("user-agent")
    session, created = await guest_service.ensure_guest_session(
        db,
        guest_session_id=body.guest_session_id,
        ip_address=client_ip,
        user_agent=user_agent,
    )

    return {
        "ok": True,
        "data": GuestBootstrapResponse(
            guest_session_id=session.id,
            created=created,
        ).model_dump(),
        "request_id": request_id,
    }
