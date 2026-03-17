"""Integration tests for the guest session service."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from packages.core.exceptions import AuthError
from packages.models.guest import GuestSession
from packages.services.guests import (
    ensure_guest_session,
    merge_guest_to_user,
    validate_guest_session,
)


class TestEnsureGuestSession:
    """Tests for ensure_guest_session."""

    @pytest.mark.asyncio
    async def test_creates_new_session(self, db_session):
        session_id = "brand-new-guest-session-1234"
        session, created = await ensure_guest_session(
            db_session, session_id, ip_address="1.2.3.4"
        )

        assert created is True, "should indicate that a new session was created"
        assert session.id == session_id, "session ID should match"
        assert session.ip_address == "1.2.3.4"

    @pytest.mark.asyncio
    async def test_returns_existing_session(self, db_session, sample_guest_session):
        session, created = await ensure_guest_session(
            db_session, sample_guest_session.id
        )

        assert created is False, "should indicate that an existing session was returned"
        assert session.id == sample_guest_session.id

    @pytest.mark.asyncio
    async def test_updates_last_seen_on_existing(self, db_session, sample_guest_session):
        old_last_seen = sample_guest_session.last_seen_at
        session, _ = await ensure_guest_session(
            db_session, sample_guest_session.id
        )

        assert session.last_seen_at >= old_last_seen, "last_seen_at should be updated"

    @pytest.mark.asyncio
    async def test_invalid_session_id_raises(self, db_session):
        with pytest.raises(AuthError, match="Invalid guest session ID"):
            await ensure_guest_session(db_session, "short")

    @pytest.mark.asyncio
    async def test_empty_session_id_raises(self, db_session):
        with pytest.raises(AuthError, match="Invalid guest session ID"):
            await ensure_guest_session(db_session, "")

    @pytest.mark.asyncio
    async def test_merged_session_raises(self, db_session, sample_guest_session, sample_user):
        sample_guest_session.merged_to_user_id = sample_user.id
        await db_session.flush()

        with pytest.raises(AuthError, match="merged"):
            await ensure_guest_session(db_session, sample_guest_session.id)


class TestValidateGuestSession:
    """Tests for validate_guest_session."""

    @pytest.mark.asyncio
    async def test_validates_existing_session(self, db_session, sample_guest_session):
        session = await validate_guest_session(db_session, sample_guest_session.id)
        assert session.id == sample_guest_session.id

    @pytest.mark.asyncio
    async def test_nonexistent_session_fails(self, db_session):
        with pytest.raises(AuthError, match="not found"):
            await validate_guest_session(db_session, "nonexistent-session-id-12345")

    @pytest.mark.asyncio
    async def test_expired_session_fails(self, db_session):
        from packages.models.guest import GuestSession

        expired_session = GuestSession(
            id="expired-guest-session-1234567890",
            last_seen_at=datetime.now(UTC) - timedelta(days=365),
            ip_address="127.0.0.1",
        )
        db_session.add(expired_session)
        await db_session.flush()

        with pytest.raises(AuthError, match="expired"):
            await validate_guest_session(db_session, expired_session.id)

    @pytest.mark.asyncio
    async def test_merged_session_fails(self, db_session, sample_guest_session, sample_user):
        sample_guest_session.merged_to_user_id = sample_user.id
        await db_session.flush()

        with pytest.raises(AuthError, match="merged"):
            await validate_guest_session(db_session, sample_guest_session.id)


class TestMergeGuestToUser:
    """Tests for merge_guest_to_user."""

    @pytest.mark.asyncio
    async def test_merge_marks_session(self, db_session, sample_guest_session, sample_user):
        await merge_guest_to_user(
            db_session, sample_guest_session.id, sample_user.id
        )

        assert sample_guest_session.merged_to_user_id == sample_user.id, (
            "merged_to_user_id should be set after merge"
        )

    @pytest.mark.asyncio
    async def test_merged_session_cannot_be_used(self, db_session, sample_guest_session, sample_user):
        await merge_guest_to_user(
            db_session, sample_guest_session.id, sample_user.id
        )

        with pytest.raises(AuthError, match="merged"):
            await ensure_guest_session(db_session, sample_guest_session.id)

    @pytest.mark.asyncio
    async def test_merge_nonexistent_session_fails(self, db_session, sample_user):
        with pytest.raises(AuthError, match="not found"):
            await merge_guest_to_user(
                db_session, "nonexistent-session-id-12345", sample_user.id
            )
