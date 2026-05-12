"""Load Wave1 seed data placeholders."""

from __future__ import annotations

from pathlib import Path

from src.ingestion.watchlist_loader import load_watchlist_csv
from src.logging_config import configure_logging


def main() -> None:
    """Validate the optional Wave1 seed watchlist CSV if present."""
    configure_logging()
    seed_path = Path("data/seed/watchlist.csv")
    if seed_path.exists():
        load_watchlist_csv(seed_path)


if __name__ == "__main__":
    main()

