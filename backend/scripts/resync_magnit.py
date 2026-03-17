"""One-off script to resync Magnit pickup points with geocoding.

Usage (from backend/ directory):
    python -m scripts.resync_magnit

Inside docker:
    docker compose exec api python -m scripts.resync_magnit
"""

from __future__ import annotations

import asyncio

from packages.core.logging import setup_logging


async def main() -> None:
    setup_logging()

    from apps.worker.jobs.sync_magnit_points import sync_magnit_points

    print("Starting Magnit points resync with geocoding...")
    await sync_magnit_points()
    print("Done!")


if __name__ == "__main__":
    asyncio.run(main())
