"""Log configuration loader — reads log_config.yaml and provides typed access."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

_DEFAULT_CONFIG: dict[str, Any] = {
    "global": {
        "log_dir": "logs",
        "default_level": "INFO",
        "format": "json",
        "stdout": True,
    },
    "retention": {
        "max_file_size_mb": 50,
        "max_files": 5,
        "max_age_days": 30,
        "archive_after_days": 7,
        "detail_max_age_days": 3,
        "cleanup_cron": "02:00",
    },
    "api": {
        "summary": {"enabled": True, "level": "INFO"},
        "detail_requests": {
            "enabled": False,
            "level": "DEBUG",
            "include_headers": True,
            "include_request_body": True,
            "include_response_body": True,
            "max_body_size": 10000,
            "mask_fields": ["password", "plain_password", "access_token", "refresh_token", "Authorization"],
        },
        "errors": {"enabled": True, "level": "WARNING", "include_traceback": True},
        "routers": {},
    },
    "worker": {
        "summary": {"enabled": True, "level": "INFO"},
        "jobs": {},
    },
    "events": {"enabled": True, "level": "INFO"},
    "integrations": {},
}


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base."""
    result = base.copy()
    for key, val in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = _deep_merge(result[key], val)
        else:
            result[key] = val
    return result


class LogConfig:
    """Typed wrapper around the YAML log configuration."""

    def __init__(self, config: dict[str, Any]) -> None:
        self._cfg = config

    # -- Global --
    @property
    def log_dir(self) -> str:
        return self._cfg["global"]["log_dir"]

    @property
    def default_level(self) -> str:
        return self._cfg["global"]["default_level"].upper()

    @property
    def log_format(self) -> str:
        return self._cfg["global"]["format"]

    @property
    def stdout_enabled(self) -> bool:
        return self._cfg["global"]["stdout"]

    # -- Retention --
    @property
    def retention(self) -> dict[str, Any]:
        return self._cfg["retention"]

    # -- API --
    @property
    def api_summary(self) -> dict[str, Any]:
        return self._cfg["api"]["summary"]

    @property
    def api_detail(self) -> dict[str, Any]:
        return self._cfg["api"]["detail_requests"]

    @property
    def api_errors(self) -> dict[str, Any]:
        return self._cfg["api"]["errors"]

    def api_router_config(self, router_name: str) -> dict[str, Any]:
        return self._cfg["api"].get("routers", {}).get(
            router_name, {"enabled": False}
        )

    # -- Worker --
    @property
    def worker_summary(self) -> dict[str, Any]:
        return self._cfg["worker"]["summary"]

    def worker_job_config(self, job_name: str) -> dict[str, Any]:
        return self._cfg["worker"].get("jobs", {}).get(
            job_name, {"enabled": False}
        )

    # -- Events --
    @property
    def events_config(self) -> dict[str, Any]:
        return self._cfg.get("events", {"enabled": True, "level": "INFO"})

    # -- Integrations --
    def integration_config(self, name: str) -> dict[str, Any]:
        return self._cfg.get("integrations", {}).get(
            name, {"enabled": False, "level": "INFO"}
        )

    # -- Raw access --
    @property
    def raw(self) -> dict[str, Any]:
        return self._cfg


def load_log_config(config_path: str | None = None) -> LogConfig:
    """Load log_config.yaml from disk, falling back to defaults."""
    if config_path is None:
        # Look next to the working directory
        config_path = os.path.join(os.getcwd(), "log_config.yaml")

    cfg = _DEFAULT_CONFIG.copy()

    path = Path(config_path)
    if path.exists():
        with open(path, encoding="utf-8") as f:
            user_cfg = yaml.safe_load(f) or {}
        cfg = _deep_merge(_DEFAULT_CONFIG, user_cfg)

    return LogConfig(cfg)


# Module-level singleton — loaded once at import time
log_config = load_log_config()
