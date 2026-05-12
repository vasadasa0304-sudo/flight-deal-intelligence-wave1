"""Run the Wave1 scheduler."""

from __future__ import annotations

import time

from src.config import load_settings
from src.ingestion.scheduler import build_scheduler
from src.logging_config import configure_logging


def main() -> None:
    """Start the placeholder scheduler process."""
    settings = load_settings()
    configure_logging(settings.log_level)
    scheduler = build_scheduler(settings)
    scheduler.start()
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        scheduler.shutdown()


if __name__ == "__main__":
    main()

