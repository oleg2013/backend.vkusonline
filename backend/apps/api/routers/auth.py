from __future__ import annotations

import structlog
from fastapi import APIRouter, Request
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from apps.api.deps import DbSession, Redis, RequestId
from packages.core.config import settings
from packages.core.rate_limit import check_rate_limit
from packages.schemas.auth import (
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
)
from packages.models.user import User, UserProfile
from packages.services import auth as auth_service

logger = structlog.get_logger("auth")

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/check-email")
async def check_email(
    body: dict,
    db: DbSession,
    request_id: RequestId,
):
    """Check if an email is already registered. Returns {exists: bool}."""
    from sqlalchemy import select
    email = (body.get("email") or "").lower().strip()
    if not email:
        return {"ok": True, "data": {"exists": False}, "request_id": request_id}
    stmt = select(User).where(User.email == email)
    result = await db.execute(stmt)
    exists = result.scalar_one_or_none() is not None
    return {"ok": True, "data": {"exists": exists}, "request_id": request_id}


@router.post("/register")
async def register(
    body: RegisterRequest,
    db: DbSession,
    redis: Redis,
    request: Request,
    request_id: RequestId,
):
    client_ip = request.client.host if request.client else "unknown"
    await check_rate_limit(redis, f"register:{client_ip}", max_requests=5, window_seconds=300)

    user, access_token, refresh_token = await auth_service.register_user(
        db,
        email=body.email,
        password=body.password,
        phone=body.phone,
        first_name=body.first_name,
        last_name=body.last_name,
    )

    return {
        "ok": True,
        "data": TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="bearer",
            expires_in=settings.jwt_access_token_expire_minutes * 60,
        ).model_dump(),
        "request_id": request_id,
    }


@router.post("/login")
async def login(
    body: LoginRequest,
    db: DbSession,
    redis: Redis,
    request: Request,
    request_id: RequestId,
):
    client_ip = request.client.host if request.client else "unknown"
    await check_rate_limit(redis, f"login:{client_ip}", max_requests=10, window_seconds=300)

    user_agent = request.headers.get("user-agent")
    user, access_token, refresh_token = await auth_service.login_user(
        db,
        email=body.email,
        password=body.password,
        user_agent=user_agent,
        ip_address=client_ip,
    )

    return {
        "ok": True,
        "data": TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="bearer",
            expires_in=settings.jwt_access_token_expire_minutes * 60,
        ).model_dump(),
        "request_id": request_id,
    }


@router.post("/refresh")
async def refresh(
    body: RefreshRequest,
    db: DbSession,
    redis: Redis,
    request: Request,
    request_id: RequestId,
):
    client_ip = request.client.host if request.client else "unknown"
    await check_rate_limit(redis, f"refresh:{client_ip}", max_requests=20, window_seconds=300)

    access_token, refresh_token = await auth_service.refresh_tokens(db, body.refresh_token)

    return {
        "ok": True,
        "data": TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="bearer",
            expires_in=settings.jwt_access_token_expire_minutes * 60,
        ).model_dump(),
        "request_id": request_id,
    }


@router.post("/logout")
async def logout(
    body: LogoutRequest,
    db: DbSession,
    request_id: RequestId,
):
    await auth_service.logout_user(db, body.refresh_token)
    return {"ok": True, "data": {"message": "Logged out"}, "request_id": request_id}


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


@router.post("/forgot-password")
async def forgot_password(
    body: ForgotPasswordRequest,
    db: DbSession,
    redis: Redis,
    request: Request,
    request_id: RequestId,
):
    """Send password reminder to email. Always returns success to prevent email enumeration."""
    client_ip = request.client.host if request.client else "unknown"
    await check_rate_limit(redis, f"forgot:{client_ip}", max_requests=3, window_seconds=300)

    email = body.email.lower().strip()
    stmt = select(User).options(selectinload(User.profile)).where(User.email == email)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if user and user.plain_password:
        user_name = email
        if user.profile:
            user_name = f"{user.profile.last_name or ''} {user.profile.first_name or ''}".strip() or email

        try:
            from packages.services.events import event_dispatcher
            await event_dispatcher.dispatch("client_event", {
                "event_name": "CLIENTREMINDPASS",
                "context": {
                    "EMAIL": email,
                    "ORDER_USER": user_name,
                    "CLIENTPASSWORD": user.plain_password,
                    "SERVER_NAME": settings.server_name,
                    "SHOP_NAME": settings.shop_name,
                    "SALE_EMAIL": settings.sale_email,
                    "SYS_SHOP_EMAIL": settings.smtp_from_email,
                },
            })
            logger.info("password_reminder_sent", email=email)
        except Exception as exc:
            logger.warning("password_reminder_failed", email=email, error=str(exc))

    await db.commit()
    return {
        "ok": True,
        "data": {"message": "Если аккаунт существует, пароль отправлен на email"},
        "request_id": request_id,
    }
