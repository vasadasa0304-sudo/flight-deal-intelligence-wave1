"""Run the Wave1 scheduler."""

from __future__ import annotations

import asyncio

from src.config import load_settings
from src.ingestion.scheduler import build_scheduler
from src.logging_config import configure_logging


async def _run() -> None:
    settings = load_settings()
    configure_logging(settings.log_level)
    scheduler = build_scheduler(settings)
    scheduler.start()
    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()


def main() -> None:
    """Start the Wave1 scheduler process."""
    asyncio.run(_run())


if __name__ == "__main__":
    main()

