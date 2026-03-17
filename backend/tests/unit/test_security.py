"""Unit tests for packages.core.security."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

from packages.core.security import (
    create_access_token,
    create_refresh_token,
    decode_access_token,
    hash_password,
    hash_token,
    verify_password,
)


class TestPasswordHashing:
    """Tests for hash_password and verify_password."""

    def test_hash_password_returns_non_empty_string(self):
        hashed = hash_password("mypassword")
        assert isinstance(hashed, str), "hash_password should return a string"
        assert len(hashed) > 0, "hash_password should return a non-empty string"

    def test_hash_password_differs_from_plain(self):
        plain = "mypassword"
        hashed = hash_password(plain)
        assert hashed != plain, "hashed password must differ from the plain text"

    def test_verify_password_correct(self):
        plain = "SecurePass123!"
        hashed = hash_password(plain)
        assert verify_password(plain, hashed) is True, "verify_password should return True for correct password"

    def test_verify_password_incorrect(self):
        hashed = hash_password("correct_password")
        assert verify_password("wrong_password", hashed) is False, (
            "verify_password should return False for incorrect password"
        )

    def test_hash_password_produces_different_hashes_for_same_input(self):
        """bcrypt includes a salt, so two hashes of the same password differ."""
        h1 = hash_password("samepassword")
        h2 = hash_password("samepassword")
        assert h1 != h2, "bcrypt hashes should differ due to different salts"
        assert verify_password("samepassword", h1) is True
        assert verify_password("samepassword", h2) is True


class TestAccessToken:
    """Tests for create_access_token and decode_access_token."""

    def test_create_and_decode_access_token(self):
        subject = "user-uuid-12345"
        token = create_access_token(subject)
        payload = decode_access_token(token)

        assert payload is not None, "decode_access_token should return a payload for a valid token"
        assert payload["sub"] == subject, "decoded subject should match the original"
        assert payload["type"] == "access", "token type should be 'access'"

    def test_create_access_token_with_extra_claims(self):
        subject = "user-uuid-99999"
        extra = {"role": "admin", "org": "vkus"}
        token = create_access_token(subject, extra=extra)
        payload = decode_access_token(token)

        assert payload is not None
        assert payload["role"] == "admin", "extra claims should be present in the token"
        assert payload["org"] == "vkus"

    def test_decode_access_token_with_wrong_secret_returns_none(self):
        token = create_access_token("user-123")
        # Patch the settings to use a different secret for decoding
        with patch("packages.core.security.settings") as mock_settings:
            mock_settings.jwt_secret_key = "completely-wrong-secret"
            mock_settings.jwt_algorithm = "HS256"
            result = decode_access_token(token)
        assert result is None, "decode_access_token should return None for a token signed with a different secret"

    def test_decode_access_token_expired_returns_none(self):
        # Create a token that expired 1 hour ago
        with patch("packages.core.security.datetime") as mock_dt:
            past = datetime.now(UTC) - timedelta(hours=2)
            mock_dt.now.return_value = past
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            token = create_access_token("user-expired")

        # Now try to decode it (current time is well after expiry)
        result = decode_access_token(token)
        assert result is None, "decode_access_token should return None for an expired token"

    def test_decode_access_token_with_invalid_string_returns_none(self):
        result = decode_access_token("not.a.valid.token")
        assert result is None, "decode_access_token should return None for an invalid token string"

    def test_decode_access_token_with_empty_string_returns_none(self):
        result = decode_access_token("")
        assert result is None, "decode_access_token should return None for an empty string"


class TestRefreshToken:
    """Tests for create_refresh_token."""

    def test_create_refresh_token_returns_string(self):
        token = create_refresh_token()
        assert isinstance(token, str), "create_refresh_token should return a string"
        assert len(token) > 20, "refresh token should be reasonably long"

    def test_create_refresh_token_generates_unique_tokens(self):
        tokens = {create_refresh_token() for _ in range(100)}
        assert len(tokens) == 100, "100 generated refresh tokens should all be unique"


class TestHashToken:
    """Tests for hash_token."""

    def test_hash_token_is_deterministic(self):
        token = "my-refresh-token-abc123"
        h1 = hash_token(token)
        h2 = hash_token(token)
        assert h1 == h2, "hash_token should produce the same hash for the same input"

    def test_hash_token_returns_hex_string(self):
        h = hash_token("some-token")
        assert len(h) == 64, "SHA-256 hex digest should be 64 characters"
        assert all(c in "0123456789abcdef" for c in h), "hash should be a valid hex string"

    def test_hash_token_different_inputs_produce_different_hashes(self):
        h1 = hash_token("token-a")
        h2 = hash_token("token-b")
        assert h1 != h2, "different inputs should produce different hashes"
