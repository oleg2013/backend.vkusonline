"""ASGI middleware for HTTP request/response logging.

Logs a summary line for every request and optionally writes full
request/response detail JSON files when `api.detail_requests.enabled`
is true in log_config.yaml.

Must be placed AFTER RequestIdMiddleware in the middleware stack
so that `scope["state"]["request_id"]` is already set.
"""

from __future__ import annotations

import json
import time
from typing import Any

import structlog
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from packages.core.log_config import log_config
from packages.core.logging import write_detail_json

logger = structlog.get_logger("apps.api.requests")


class RequestLogMiddleware:
    """Pure ASGI middleware — does NOT use BaseHTTPMiddleware."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self._detail_enabled = log_config.api_detail.get("enabled", False)
        self._max_body = log_config.api_detail.get("max_body_size", 10000)
        self._include_req_body = log_config.api_detail.get("include_request_body", True)
        self._include_resp_body = log_config.api_detail.get("include_response_body", True)
        self._include_headers = log_config.api_detail.get("include_headers", True)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "")
        path = scope.get("path", "")

        # Skip health checks from log noise
        if path.endswith("/health"):
            await self.app(scope, receive, send)
            return

        start_time = time.monotonic()
        request_id = scope.get("state", {}).get("request_id", "")

        # Collect request body if detail mode is on
        request_body_chunks: list[bytes] = []

        async def receive_wrapper() -> Message:
            message = await receive()
            if self._detail_enabled and self._include_req_body:
                if message.get("type") == "http.request":
                    body = message.get("body", b"")
                    if body:
                        request_body_chunks.append(body)
            return message

        # Collect response status and body
        response_status: int = 0
        response_body_chunks: list[bytes] = []
        response_headers: list[tuple[bytes, bytes]] = []

        async def send_wrapper(message: Message) -> None:
            nonlocal response_status, response_headers
            if message["type"] == "http.response.start":
                response_status = message.get("status", 0)
                response_headers = list(message.get("headers", []))
            elif message["type"] == "http.response.body":
                if self._detail_enabled and self._include_resp_body:
                    body = message.get("body", b"")
                    if body:
                        response_body_chunks.append(body)
            await send(message)

        try:
            await self.app(scope, receive_wrapper, send_wrapper)
        except Exception:
            response_status = 500
            raise
        finally:
            duration_ms = round((time.monotonic() - start_time) * 1000, 1)

            # Extract user_id from scope state if available
            state = scope.get("state", {})
            user_id = state.get("user_id", "")

            # Extract client IP
            client = scope.get("client")
            ip = client[0] if client else ""

            # Summary log
            logger.info(
                "http_request",
                request_id=request_id[:8] if request_id else "",
                method=method,
                path=path,
                status=response_status,
                duration_ms=duration_ms,
                user_id=user_id or None,
                ip=ip,
            )

            # Detail JSON
            if self._detail_enabled:
                detail: dict[str, Any] = {
                    "request_id": request_id,
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "request": {
                        "method": method,
                        "path": path,
                        "query_string": scope.get("query_string", b"").decode("utf-8", errors="replace"),
                    },
                    "response": {
                        "status": response_status,
                        "duration_ms": duration_ms,
                    },
                }

                if self._include_headers:
                    req_headers = {}
                    for h_name, h_val in scope.get("headers", []):
                        req_headers[h_name.decode("latin-1")] = h_val.decode("latin-1")
                    detail["request"]["headers"] = req_headers

                    resp_headers = {}
                    for h_name, h_val in response_headers:
                        resp_headers[h_name.decode("latin-1")] = h_val.decode("latin-1")
                    detail["response"]["headers"] = resp_headers

                if self._include_req_body and request_body_chunks:
                    raw = b"".join(request_body_chunks)
                    body_str = raw.decode("utf-8", errors="replace")
                    if len(body_str) > self._max_body:
                        body_str = body_str[:self._max_body] + "...(truncated)"
                    try:
                        detail["request"]["body"] = json.loads(body_str)
                    except (json.JSONDecodeError, ValueError):
                        detail["request"]["body"] = body_str

                if self._include_resp_body and response_body_chunks:
                    raw = b"".join(response_body_chunks)
                    body_str = raw.decode("utf-8", errors="replace")
                    if len(body_str) > self._max_body:
                        body_str = body_str[:self._max_body] + "...(truncated)"
                    try:
                        detail["response"]["body"] = json.loads(body_str)
                    except (json.JSONDecodeError, ValueError):
                        detail["response"]["body"] = body_str

                write_detail_json(detail)
