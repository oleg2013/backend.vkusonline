"""Worker job: log rotation, archival, and cleanup.

Runs daily (configured via retention.cleanup_cron in log_config.yaml).
Handles:
  1. Delete detail JSON files older than detail_max_age_days
  2. Archive (tar.gz) daily request folders older than archive_after_days
  3. Delete archives older than max_age_days
  4. Delete excess rotated log files beyond max_files
"""

from __future__ import annotations

import os
import shutil
import tarfile
import time
from datetime import datetime, timedelta
from pathlib import Path

import structlog

from packages.core.log_config import log_config

logger = structlog.get_logger(__name__)


def _ts_from_dirname(name: str) -> datetime | None:
    """Parse YYYY-MM-DD from a directory name."""
    try:
        return datetime.strptime(name, "%Y-%m-%d")
    except ValueError:
        return None


def _ts_from_archive(name: str) -> datetime | None:
    """Parse date from archive name like api_requests_2026-03-10.tar.gz."""
    try:
        # Extract date part
        parts = name.replace(".tar.gz", "").split("_")
        date_str = parts[-1]
        return datetime.strptime(date_str, "%Y-%m-%d")
    except (ValueError, IndexError):
        return None


async def cleanup_logs() -> None:
    """Main cleanup entry point, called by APScheduler."""
    retention = log_config.retention
    log_dir = Path(log_config.log_dir)

    if not log_dir.exists():
        logger.info("cleanup_logs_skip", reason="log_dir does not exist")
        return

    detail_max_days = retention.get("detail_max_age_days", 3)
    archive_after_days = retention.get("archive_after_days", 7)
    max_age_days = retention.get("max_age_days", 30)
    max_files = retention.get("max_files", 5)

    now = datetime.now()
    stats = {"detail_deleted": 0, "archived": 0, "archives_deleted": 0, "rotated_deleted": 0}

    # --- 1. Delete old detail JSON files ---
    requests_dir = log_dir / "api" / "requests"
    if requests_dir.exists():
        cutoff = now - timedelta(days=detail_max_days)
        for day_dir in sorted(requests_dir.iterdir()):
            if not day_dir.is_dir():
                continue
            dt = _ts_from_dirname(day_dir.name)
            if dt and dt < cutoff:
                count = sum(1 for _ in day_dir.glob("*.json"))
                shutil.rmtree(day_dir, ignore_errors=True)
                stats["detail_deleted"] += count
                logger.info("cleanup_detail_deleted", dir=day_dir.name, files=count)

    # --- 2. Archive old daily request folders ---
    archive_dir = log_dir / "_archive"
    if requests_dir.exists():
        cutoff = now - timedelta(days=archive_after_days)
        for day_dir in sorted(requests_dir.iterdir()):
            if not day_dir.is_dir():
                continue
            dt = _ts_from_dirname(day_dir.name)
            if dt and dt < cutoff:
                archive_dir.mkdir(parents=True, exist_ok=True)
                archive_name = f"api_requests_{day_dir.name}.tar.gz"
                archive_path = archive_dir / archive_name
                if not archive_path.exists():
                    try:
                        with tarfile.open(str(archive_path), "w:gz") as tar:
                            tar.add(str(day_dir), arcname=day_dir.name)
                        shutil.rmtree(day_dir, ignore_errors=True)
                        stats["archived"] += 1
                        logger.info("cleanup_archived", dir=day_dir.name, archive=archive_name)
                    except Exception as exc:
                        logger.warning("cleanup_archive_error", dir=day_dir.name, error=str(exc))

    # --- 3. Delete old archives ---
    if archive_dir.exists():
        cutoff = now - timedelta(days=max_age_days)
        for archive_file in sorted(archive_dir.glob("*.tar.gz")):
            dt = _ts_from_archive(archive_file.name)
            if dt and dt < cutoff:
                archive_file.unlink(missing_ok=True)
                stats["archives_deleted"] += 1
                logger.info("cleanup_archive_deleted", file=archive_file.name)

    # --- 4. Clean up excess rotated log files ---
    # RotatingFileHandler creates .log.1, .log.2, etc.
    for log_file in log_dir.rglob("*.log"):
        parent = log_file.parent
        base_name = log_file.name
        rotated = sorted(parent.glob(f"{base_name}.*"), reverse=True)
        if len(rotated) > max_files:
            for excess in rotated[max_files:]:
                excess.unlink(missing_ok=True)
                stats["rotated_deleted"] += 1

    logger.info("cleanup_logs_complete", **stats)
