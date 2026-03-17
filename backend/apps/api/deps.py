from __future__ import annotations

from typing import Annotated

import redis.asyncio as aioredis
from fastapi import Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from packages.core.config import settings
from packages.core.db import get_db
from packages.core.exceptions import AuthError, ForbiddenError
from packages.core.redis import get_redis
from packages.core.security import decode_access_token

DbSession = Annotated[AsyncSession, Depends(get_db)]
Redis = Annotated[aioredis.Redis, Depends(get_redis)]


def get_request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


RequestId = Annotated[str | None, Depends(get_request_id)]


async def get_current_user_id(
    authorization: Annotated[str | None, Header()] = None,
) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise AuthError("Missing or invalid Authorization header")
    token = authorization.removeprefix("Bearer ")
    payload = decode_access_token(token)
    if not payload or "sub" not in payload:
        raise AuthError("Invalid or expired access token")
    return payload["sub"]


CurrentUserId = Annotated[str, Depends(get_current_user_id)]


async def get_optional_user_id(
    authorization: Annotated[str | None, Header()] = None,
) -> str | None:
    if not authorization or not authorization.startswith("Bearer "):
        return None
    token = authorization.removeprefix("Bearer ")
    payload = decode_access_token(token)
    if not payload or "sub" not in payload:
        return None
    return payload["sub"]


OptionalUserId = Annotated[str | None, Depends(get_optional_user_id)]


async def get_guest_session_id(
    x_guest_session_id: Annotated[str | None, Header()] = None,
) -> str:
    if not x_guest_session_id:
        raise AuthError("Missing X-Guest-Session-ID header")
    return x_guest_session_id


GuestSessionId = Annotated[str, Depends(get_guest_session_id)]


async def get_optional_guest_session_id(
    x_guest_session_id: Annotated[str | None, Header()] = None,
) -> str | None:
    return x_guest_session_id


OptionalGuestSessionId = Annotated[str | None, Depends(get_optional_guest_session_id)]


ADMIN_TOKEN = settings.app_secret_key


async def require_admin(
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    if not authorization:
        raise ForbiddenError("Admin access required")
    token = authorization.removeprefix("Bearer ").strip()
    if token != ADMIN_TOKEN:
        raise ForbiddenError("Invalid admin token")
