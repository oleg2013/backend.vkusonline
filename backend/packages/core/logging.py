"""Structured logging system with file-based routing.

Routes log records to multiple files based on logger name:
  - api/api.log, api/errors.log, api/{router}/{router}.log
  - worker/worker.log, worker/{job}/{job}.log
  - events/events.log
  - integrations/{provider}/{provider}.log

Configuration is driven by log_config.yaml (see packages.core.log_config).
"""

from __future__ import annotations

import json
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

import structlog

from packages.core.log_config import log_config

# ---------------------------------------------------------------------------
# Monkey-patch structlog.get_logger AT IMPORT TIME so that every module
# that does `logger = structlog.get_logger(__name__)` automatically gets
# `_logger_name` bound. This MUST happen before any other module imports
# structlog and calls get_logger.
# ---------------------------------------------------------------------------

_original_structlog_get_logger = structlog.get_logger


def _patched_get_logger(*args: Any, **kwargs: Any) -> Any:
    log = _original_structlog_get_logger(*args, **kwargs)
    name = args[0] if args and isinstance(args[0], str) else ""
    if name:
        return log.bind(_logger_name=name)
    return log


structlog.get_logger = _patched_get_logger  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Sensitive field masking
# ---------------------------------------------------------------------------

_MASK_FIELDS: set[str] = set()


def _mask_value(val: str, visible: int = 8) -> str:
    if len(val) <= visible:
        return "***"
    return val[:visible] + "***"


def _mask_dict(data: Any, fields: set[str]) -> Any:
    if not fields:
        return data
    if isinstance(data, dict):
        return {
            k: (_mask_value(str(v)) if k.lower() in fields else _mask_dict(v, fields))
            for k, v in data.items()
        }
    if isinstance(data, list):
        return [_mask_dict(item, fields) for item in data]
    return data


# ---------------------------------------------------------------------------
# Log directory + file handler registry
# ---------------------------------------------------------------------------

_log_dir: Path | None = None


def _ensure_log_dir(*parts: str) -> Path:
    global _log_dir
    if _log_dir is None:
        _log_dir = Path(log_config.log_dir)
    target = _log_dir.joinpath(*parts)
    target.mkdir(parents=True, exist_ok=True)
    return target


_handlers: dict[str, RotatingFileHandler] = {}
_MAX_BYTES = log_config.retention.get("max_file_size_mb", 50) * 1024 * 1024
_BACKUP_COUNT = log_config.retention.get("max_files", 5)


def _get_file_handler(subdir: str, filename: str) -> RotatingFileHandler:
    key = f"{subdir}/{filename}"
    if key not in _handlers:
        dirpath = _ensure_log_dir(subdir)
        filepath = dirpath / filename
        handler = RotatingFileHandler(
            str(filepath), maxBytes=_MAX_BYTES, backupCount=_BACKUP_COUNT, encoding="utf-8",
        )
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(logging.Formatter("%(message)s"))
        _handlers[key] = handler
    return _handlers[key]


def _emit(handler: RotatingFileHandler, line: str) -> None:
    record = logging.LogRecord("", logging.INFO, "", 0, line, None, None)
    handler.emit(record)


# ---------------------------------------------------------------------------
# Routing maps: logger name prefix → category
# ---------------------------------------------------------------------------

_ROUTER_MAP: dict[str, str] = {
    "apps.api.routers.auth": "auth",
    "apps.api.routers.checkout": "checkout",
    "apps.api.routers.payments": "payments",
    "apps.api.routers.webhooks": "webhooks",
    "apps.api.routers.delivery": "delivery",
    "apps.api.routers.delivery_5post": "delivery",
    "apps.api.routers.delivery_magnit": "delivery",
    "apps.api.routers.geo": "geo",
    "apps.api.routers.admin": "admin",
    "apps.api.routers.orders": "orders",
    "apps.api.routers.public_orders": "public_orders",
    "apps.api.routers.catalog": "catalog",
    "apps.api.routers.cart": "cart",
    "apps.api.routers.me": "auth",
    "apps.api.routers.guest": "auth",
    "apps.api.middleware": "api_middleware",
    "apps.api.requests": "api_middleware",
    "packages.services.auth": "auth",
    "packages.services.checkout": "checkout",
    "packages.services.cart": "cart",
    "packages.services.catalog": "catalog",
    "packages.services.delivery": "delivery",
    "packages.services.orders": "orders",
    "packages.services.payments": "payments",
    "packages.services.guests": "auth",
    "packages.services.discounts": "checkout",
    "packages.services.email": "email",
}

_JOB_MAP: dict[str, str] = {
    "apps.worker.jobs.send_email": "email_queue",
    "apps.worker.jobs.cancel_unpaid_orders": "cancel_unpaid",
    "apps.worker.jobs.reconcile_pending_payments": "reconcile_payments",
    "apps.worker.jobs.sync_5post_points": "sync_5post",
    "apps.worker.jobs.sync_magnit_points": "sync_magnit",
    "apps.worker.jobs.poll_magnit_statuses": "poll_magnit",
    "apps.worker.jobs.cleanup_guest_sessions": "cleanup_guests",
    "apps.worker.jobs.cleanup_idempotency": "cleanup_idempotency",
    "apps.worker.jobs.cleanup_logs": "cleanup_logs",
}

_INTEGRATION_MAP: dict[str, str] = {
    "integrations.yookassa": "yookassa",
    "integrations.fivepost": "fivepost",
    "integrations.magnit": "magnit",
    "integrations.dadata": "dadata",
    "packages.integrations.yookassa": "yookassa",
    "packages.integrations.fivepost": "fivepost",
    "packages.integrations.magnit": "magnit",
    "packages.integrations.geo": "dadata",
}


def _route_to_files(logger_name: str, level: int, log_line: str) -> None:
    """Route a formatted log line to the appropriate file handler(s)."""
    routed = False

    for prefix, router_name in _ROUTER_MAP.items():
        if logger_name.startswith(prefix):
            cfg = log_config.api_router_config(router_name)
            if cfg.get("enabled", False):
                _emit(_get_file_handler(f"api/{router_name}", f"{router_name}.log"), log_line)
            if log_config.api_summary.get("enabled", True):
                _emit(_get_file_handler("api", "api.log"), log_line)
            routed = True
            break

    if not routed:
        for prefix, job_name in _JOB_MAP.items():
            if logger_name.startswith(prefix):
                cfg = log_config.worker_job_config(job_name)
                if cfg.get("enabled", False):
                    _emit(_get_file_handler(f"worker/{job_name}", f"{job_name}.log"), log_line)
                if log_config.worker_summary.get("enabled", True):
                    _emit(_get_file_handler("worker", "worker.log"), log_line)
                routed = True
                break

    if not routed:
        for prefix, provider in _INTEGRATION_MAP.items():
            if logger_name.startswith(prefix):
                cfg = log_config.integration_config(provider)
                if cfg.get("enabled", False):
                    _emit(_get_file_handler(f"integrations/{provider}", f"{provider}.log"), log_line)
                routed = True
                break

    if not routed and logger_name.startswith("packages.services.events"):
        cfg = log_config.events_config
        if cfg.get("enabled", False):
            _emit(_get_file_handler("events", "events.log"), log_line)
        routed = True

    if not routed and logger_name.startswith("apps.worker"):
        if log_config.worker_summary.get("enabled", True):
            _emit(_get_file_handler("worker", "worker.log"), log_line)

    # Errors → errors.log
    if level >= logging.WARNING:
        is_api = any(logger_name.startswith(p) for p in _ROUTER_MAP) or logger_name.startswith("apps.api")
        is_worker = any(logger_name.startswith(p) for p in _JOB_MAP) or logger_name.startswith("apps.worker")
        if is_api:
            _emit(_get_file_handler("api", "errors.log"), log_line)
        if is_worker:
            _emit(_get_file_handler("worker", "errors.log"), log_line)


# ---------------------------------------------------------------------------
# structlog processors
# ---------------------------------------------------------------------------

def _file_routing_processor(
    logger: Any, method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """Serialize to JSON, route to file handlers, pass through for stdout."""
    logger_name = event_dict.get("_logger_name", "") or ""

    output: dict[str, Any] = {
        "ts": event_dict.get("timestamp", ""),
        "level": event_dict.get("level", method_name),
        "logger": logger_name,
        "msg": event_dict.get("event", ""),
    }

    for ctx_key in ("request_id", "method", "path"):
        val = event_dict.get(ctx_key)
        if val:
            output[ctx_key] = val

    skip = {"timestamp", "level", "event", "_logger_name", "_positional_args",
            "request_id", "method", "path"}
    extra = {k: v for k, v in event_dict.items() if k not in skip}
    if extra:
        output["data"] = _mask_dict(extra, _MASK_FIELDS)

    log_line = json.dumps(output, ensure_ascii=False, default=str)
    level_num = getattr(logging, str(output["level"]).upper(), logging.INFO)
    _route_to_files(logger_name, level_num, log_line)

    # Remove internal key before passing to stdout renderer
    event_dict.pop("_logger_name", None)
    event_dict.pop("_positional_args", None)
    return event_dict


def _inject_logger_name(
    logger: Any, method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """Extract logger name from structlog's positional args or bound state."""
    # structlog.get_logger("name") stores name in _initial_positional_args
    # or in _context for bound loggers
    name = ""

    # Way 1: positional args from structlog.get_logger("name")
    pos_args = event_dict.get("_positional_args")
    if pos_args and isinstance(pos_args, tuple) and len(pos_args) > 0:
        name = str(pos_args[0])

    # Way 2: from our wrapper that sets _logger_name in context
    if not name:
        name = event_dict.get("_logger_name", "")

    event_dict["_logger_name"] = name
    return event_dict


# ---------------------------------------------------------------------------
# Detail JSON logging
# ---------------------------------------------------------------------------

def write_detail_json(data: dict[str, Any]) -> None:
    """Write a full request/response detail JSON file."""
    import time as _time

    ts = _time.strftime("%Y-%m-%d")
    dirpath = _ensure_log_dir("api", "requests", ts)

    existing = sorted(dirpath.glob("*.json"))
    seq = len(existing) + 1

    rid = str(data.get("request_id", ""))[:8]
    ts_time = _time.strftime("%H-%M-%S")
    filename = f"{seq:04d}_{rid}_{ts_time}.json"

    masked = _mask_dict(data, _MASK_FIELDS)
    filepath = dirpath / filename
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(masked, f, ensure_ascii=False, indent=2, default=str)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def setup_logging() -> None:
    """Initialize the logging system based on log_config.yaml."""
    global _MASK_FIELDS

    level_name = log_config.default_level
    log_level = getattr(logging, level_name, logging.INFO)

    mask_fields: set[str] = set()
    for f in log_config.api_detail.get("mask_fields", []):
        mask_fields.add(f.lower())
    for provider in ("yookassa", "fivepost", "magnit", "dadata"):
        for f in log_config.integration_config(provider).get("mask_fields", []):
            mask_fields.add(f.lower())
    _MASK_FIELDS = mask_fields

    _ensure_log_dir("api")
    _ensure_log_dir("worker")
    _ensure_log_dir("events")
    _ensure_log_dir("integrations")

    processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        _inject_logger_name,
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.dev.set_exc_info,
        structlog.processors.TimeStamper(fmt="iso"),
        _file_routing_processor,
    ]

    if log_config.log_format == "json":
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer())

    factory = structlog.PrintLoggerFactory()
    if not log_config.stdout_enabled:
        factory = structlog.PrintLoggerFactory(file=open(os.devnull, "w"))

    # Reset any previously cached loggers so our new config takes effect
    structlog.reset_defaults()

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=factory,
        cache_logger_on_first_use=False,  # False: loggers always use latest config
    )

    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=log_level)
    for noisy in ("httpx", "httpcore", "asyncio", "sqlalchemy.engine"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Get a structlog logger with a name for file routing."""
    return structlog.get_logger(name) if name else structlog.get_logger()
