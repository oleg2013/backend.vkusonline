"""Integration tests for the full authentication flow.

Tests register, login, refresh, logout, and duplicate-email scenarios
using the auth service functions directly with a real (in-memory SQLite) database.
"""

from __future__ import annotations

import pytest

from packages.core.exceptions import AuthError, ConflictError, ValidationError
from packages.core.security import hash_token
from packages.services.auth import (
    login_user,
    logout_user,
    refresh_tokens,
    register_user,
)


class TestRegisterUser:
    """Tests for register_user."""

    @pytest.mark.asyncio
    async def test_register_creates_user(self, db_session):
        user, access_token, refresh_token = await register_user(
            db_session,
            email="new@example.com",
            password="StrongPass1!",
            first_name="New",
            last_name="User",
        )

        assert user is not None, "register should return a user"
        assert user.email == "new@example.com", "email should match"
        assert user.is_active is True, "new user should be active"
        assert len(access_token) > 0, "access token should be non-empty"
        assert len(refresh_token) > 0, "refresh token should be non-empty"

    @pytest.mark.asyncio
    async def test_register_duplicate_email_fails(self, db_session):
        await register_user(
            db_session,
            email="dup@example.com",
            password="StrongPass1!",
        )

        with pytest.raises(ConflictError, match="already exists"):
            await register_user(
                db_session,
                email="dup@example.com",
                password="AnotherPass1!",
            )

    @pytest.mark.asyncio
    async def test_register_invalid_email_fails(self, db_session):
        with pytest.raises(ValidationError, match="Invalid email"):
            await register_user(
                db_session,
                email="not-an-email",
                password="StrongPass1!",
            )

    @pytest.mark.asyncio
    async def test_register_short_password_fails(self, db_session):
        with pytest.raises(ValidationError, match="at least 8"):
            await register_user(
                db_session,
                email="short@example.com",
                password="short",
            )

    @pytest.mark.asyncio
    async def test_register_with_phone(self, db_session):
        user, _, _ = await register_user(
            db_session,
            email="phone@example.com",
            password="StrongPass1!",
            phone="+79991234567",
        )
        assert user.phone == "+79991234567", "phone should be stored"


class TestLoginUser:
    """Tests for login_user."""

    @pytest.mark.asyncio
    async def test_login_with_correct_credentials(self, db_session):
        await register_user(
            db_session,
            email="login@example.com",
            password="CorrectPass1!",
        )

        user, access_token, refresh_token = await login_user(
            db_session,
            email="login@example.com",
            password="CorrectPass1!",
        )

        assert user is not None, "login should return a user"
        assert user.email == "login@example.com"
        assert len(access_token) > 0
        assert len(refresh_token) > 0

    @pytest.mark.asyncio
    async def test_login_with_wrong_password_fails(self, db_session):
        await register_user(
            db_session,
            email="wrong@example.com",
            password="CorrectPass1!",
        )

        with pytest.raises(AuthError, match="Invalid email or password"):
            await login_user(
                db_session,
                email="wrong@example.com",
                password="WrongPassword!",
            )

    @pytest.mark.asyncio
    async def test_login_nonexistent_user_fails(self, db_session):
        with pytest.raises(AuthError, match="Invalid email or password"):
            await login_user(
                db_session,
                email="nobody@example.com",
                password="AnyPassword1!",
            )

    @pytest.mark.asyncio
    async def test_login_case_insensitive_email(self, db_session):
        await register_user(
            db_session,
            email="CaseTest@Example.com",
            password="StrongPass1!",
        )

        user, _, _ = await login_user(
            db_session,
            email="casetest@example.com",
            password="StrongPass1!",
        )
        assert user is not None, "login should work with different email casing"


class TestRefreshTokens:
    """Tests for refresh_tokens."""

    @pytest.mark.asyncio
    async def test_refresh_returns_new_tokens(self, db_session):
        _, _, refresh_raw = await register_user(
            db_session,
            email="refresh@example.com",
            password="StrongPass1!",
        )

        new_access, new_refresh = await refresh_tokens(db_session, refresh_raw)

        assert len(new_access) > 0, "new access token should be non-empty"
        assert len(new_refresh) > 0, "new refresh token should be non-empty"
        assert new_refresh != refresh_raw, "new refresh token should differ from old"

    @pytest.mark.asyncio
    async def test_refresh_with_revoked_token_fails(self, db_session):
        _, _, refresh_raw = await register_user(
            db_session,
            email="revoked@example.com",
            password="StrongPass1!",
        )

        # Use the token once (rotates it)
        await refresh_tokens(db_session, refresh_raw)

        # Try using the old (now revoked) token again
        with pytest.raises(AuthError, match="Invalid refresh token"):
            await refresh_tokens(db_session, refresh_raw)

    @pytest.mark.asyncio
    async def test_refresh_with_invalid_token_fails(self, db_session):
        with pytest.raises(AuthError, match="Invalid refresh token"):
            await refresh_tokens(db_session, "completely-invalid-token")


class TestLogout:
    """Tests for logout_user."""

    @pytest.mark.asyncio
    async def test_logout_revokes_refresh_token(self, db_session):
        _, _, refresh_raw = await register_user(
            db_session,
            email="logout@example.com",
            password="StrongPass1!",
        )

        await logout_user(db_session, refresh_raw)

        # After logout, the refresh token should be revoked
        with pytest.raises(AuthError, match="Invalid refresh token"):
            await refresh_tokens(db_session, refresh_raw)

    @pytest.mark.asyncio
    async def test_logout_with_unknown_token_is_no_op(self, db_session):
        # Should not raise
        await logout_user(db_session, "unknown-token-abc")
