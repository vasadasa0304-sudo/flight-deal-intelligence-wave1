"""Load Wave1 seed CSVs into PostgreSQL."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Sequence

from src.config import load_settings
from src.db_helpers import get_engine
from src.ingestion.watchlist_loader import (
    format_load_summary,
    load_seed_data,
    summary_from_dataset,
    validate_seed_files,
)
from src.logging_config import configure_logging

logger = logging.getLogger(__name__)


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint for Wave1 seed validation and loading."""
    configure_logging()
    args = _parse_args(argv)
    seed_dir = Path("data/seed")

    logger.info("Starting Wave1 seed loader. seed_dir=%s", seed_dir)
    if args.validate_only:
        dataset = validate_seed_files(seed_dir)
        print("Validation passed. No rows inserted.")
        print(format_load_summary(summary_from_dataset(dataset)))
        return 0

    if args.truncate:
        print(
            "WARNING: --truncate will truncate Wave1 seed tables and dependent rows "
            "inside the load transaction before inserting seed data."
        )

    settings = load_settings()
    engine = get_engine(settings)
    try:
        summary = load_seed_data(engine, seed_dir, truncate=args.truncate)
    finally:
        engine.dispose()

    print(format_load_summary(summary))
    return 0


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Load Wave1 seed CSV files into PostgreSQL.")
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Run seed CSV validation and exit without inserting rows.",
    )
    parser.add_argument(
        "--truncate",
        action="store_true",
        help="Truncate the five Wave1 seed tables before loading.",
    )
    return parser.parse_args(argv)


if __name__ == "__main__":
    raise SystemExit(main())
