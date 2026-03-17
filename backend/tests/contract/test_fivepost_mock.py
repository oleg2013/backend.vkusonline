"""Contract tests for 5Post API integration using respx mocks.

Validates the JWT auth flow and paginated pickup point loading.
"""

from __future__ import annotations

import base64
import json
import time

import pytest
import respx
from httpx import Response

from packages.integrations.fivepost.client import FivePostClient
from tests.fixtures.provider_payloads.fivepost import (
    PICKUP_POINTS_RESPONSE,
)


def _make_jwt(exp: float | None = None) -> str:
    """Create a fake JWT with a valid ``exp`` claim for testing."""
    header = base64.urlsafe_b64encode(
        json.dumps({"alg": "RS256", "typ": "JWT"}).encode()
    ).rstrip(b"=").decode()

    exp_time = exp or (time.time() + 3600)
    payload = base64.urlsafe_b64encode(
        json.dumps({"sub": "test", "exp": exp_time}).encode()
    ).rstrip(b"=").decode()

    signature = base64.urlsafe_b64encode(b"fake-signature").rstrip(b"=").decode()

    return f"{header}.{payload}.{signature}"


@pytest.fixture
def fivepost_client() -> FivePostClient:
    return FivePostClient(
        base_url="https://api-omni.x5.ru",
        api_key="test-api-key",
        warehouse_id="test-warehouse-id",
    )


class TestFivePostJwtAuth:
    """Tests for the JWT authentication flow."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_jwt_auth_flow(self, fivepost_client):
        """Client should obtain a JWT before making authenticated requests."""
        jwt_token = _make_jwt()

        # Mock JWT endpoint
        respx.post(
            "https://api-omni.x5.ru/jwt-generate-claims/rs256/1"
        ).mock(
            return_value=Response(
                200,
                json={"status": "ok", "jwt": jwt_token},
            )
        )

        # Mock a simple authenticated endpoint
        respx.post(
            "https://api-omni.x5.ru/api/v1/pickuppoints/query"
        ).mock(
            return_value=Response(200, json=PICKUP_POINTS_RESPONSE)
        )

        points = await fivepost_client.get_all_pickup_points()

        # Verify JWT was requested
        jwt_calls = [
            c for c in respx.calls
            if "jwt-generate-claims" in str(c.request.url)
        ]
        assert len(jwt_calls) >= 1, "JWT endpoint should have been called"

        # Verify the authenticated request used the token
        pickup_calls = [
            c for c in respx.calls
            if "pickuppoints/query" in str(c.request.url)
        ]
        assert len(pickup_calls) >= 1
        auth_header = pickup_calls[0].request.headers.get("authorization", "")
        assert auth_header.startswith("Bearer "), (
            "authenticated requests should include a Bearer token"
        )

    @pytest.mark.asyncio
    @respx.mock
    async def test_jwt_reuses_valid_token(self, fivepost_client):
        """Client should reuse a valid JWT instead of requesting a new one."""
        jwt_token = _make_jwt()

        jwt_route = respx.post(
            "https://api-omni.x5.ru/jwt-generate-claims/rs256/1"
        ).mock(
            return_value=Response(
                200,
                json={"status": "ok", "jwt": jwt_token},
            )
        )

        pickup_route = respx.post(
            "https://api-omni.x5.ru/api/v1/pickuppoints/query"
        ).mock(
            return_value=Response(200, json=PICKUP_POINTS_RESPONSE)
        )

        # Make two requests
        await fivepost_client.get_all_pickup_points()
        await fivepost_client.get_all_pickup_points()

        # JWT should only be requested once (token is cached)
        jwt_call_count = len([
            c for c in respx.calls
            if "jwt-generate-claims" in str(c.request.url)
        ])
        assert jwt_call_count == 1, (
            f"JWT should be requested only once, was requested {jwt_call_count} times"
        )


class TestFivePostPickupPointsPagination:
    """Tests for get_all_pickup_points pagination."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_single_page_response(self, fivepost_client):
        jwt_token = _make_jwt()

        respx.post(
            "https://api-omni.x5.ru/jwt-generate-claims/rs256/1"
        ).mock(
            return_value=Response(
                200,
                json={"status": "ok", "jwt": jwt_token},
            )
        )

        respx.post(
            "https://api-omni.x5.ru/api/v1/pickuppoints/query"
        ).mock(
            return_value=Response(200, json=PICKUP_POINTS_RESPONSE)
        )

        points = await fivepost_client.get_all_pickup_points()

        assert len(points) == 2, (
            f"should parse 2 pickup points from mock, got {len(points)}"
        )
        assert points[0].id == "PP-001"
        assert points[0].city == "Moscow"
        assert points[1].id == "PP-002"

    @pytest.mark.asyncio
    @respx.mock
    async def test_multi_page_response(self, fivepost_client):
        jwt_token = _make_jwt()

        respx.post(
            "https://api-omni.x5.ru/jwt-generate-claims/rs256/1"
        ).mock(
            return_value=Response(
                200,
                json={"status": "ok", "jwt": jwt_token},
            )
        )

        # Page 0 (totalPages=2 means there is a page 1)
        page_0 = {
            "totalPages": 2,
            "totalElements": 3,
            "content": [PICKUP_POINTS_RESPONSE["content"][0]],
        }
        page_1 = {
            "totalPages": 2,
            "totalElements": 3,
            "content": [PICKUP_POINTS_RESPONSE["content"][1]],
        }

        call_count = {"n": 0}
        original_pages = [page_0, page_1]

        def _side_effect(request):
            body = json.loads(request.content)
            page_num = body.get("pageNumber", 0)
            if page_num < len(original_pages):
                return Response(200, json=original_pages[page_num])
            return Response(200, json={"totalPages": 2, "content": []})

        respx.post(
            "https://api-omni.x5.ru/api/v1/pickuppoints/query"
        ).mock(side_effect=_side_effect)

        points = await fivepost_client.get_all_pickup_points()

        assert len(points) == 2, (
            f"should have loaded 2 points across 2 pages, got {len(points)}"
        )

    @pytest.mark.asyncio
    @respx.mock
    async def test_pickup_point_parsing(self, fivepost_client):
        jwt_token = _make_jwt()

        respx.post(
            "https://api-omni.x5.ru/jwt-generate-claims/rs256/1"
        ).mock(
            return_value=Response(
                200,
                json={"status": "ok", "jwt": jwt_token},
            )
        )

        respx.post(
            "https://api-omni.x5.ru/api/v1/pickuppoints/query"
        ).mock(
            return_value=Response(200, json=PICKUP_POINTS_RESPONSE)
        )

        points = await fivepost_client.get_all_pickup_points()
        point = points[0]

        assert point.name == "Postamt Moscow Center"
        assert point.type == "POSTAMAT"
        assert len(point.rates) == 1
        assert point.rates[0].rate_value_with_vat == 200.0
        assert point.cell_limits is not None
        assert point.cell_limits.max_length_mm == 600
