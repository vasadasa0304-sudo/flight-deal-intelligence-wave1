"""Build Wave1 rolling median baselines."""

from __future__ import annotations

import argparse
import logging
from datetime import UTC, date, datetime
from typing import Sequence

from sqlalchemy.orm import Session

from src.baselines.baseline_job import build_baselines
from src.config import load_settings
from src.db_helpers import get_engine
from src.logging_config import configure_logging

logger = logging.getLogger(__name__)


def main(argv: Sequence[str] | None = None) -> int:
    """Build baselines for the given date and optional watch_id."""
    args = _parse_args(argv)
    baseline_date = (
        date.fromisoformat(args.date) if args.date else datetime.now(UTC).date()
    )

    configure_logging()
    settings = load_settings()
    engine = get_engine(settings)
    try:
        with Session(engine) as session:
            count = build_baselines(session, baseline_date, watch_id=args.watch_id)
            session.commit()
    finally:
        engine.dispose()

    print(f"Baselines built: {count} row(s) for {baseline_date}")
    return 0


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build Wave1 rolling median baselines.")
    parser.add_argument(
        "--date",
        default=None,
        metavar="YYYY-MM-DD",
        help="Baseline date (default: today UTC).",
    )
    parser.add_argument(
        "--watch-id",
        type=int,
        default=None,
        metavar="N",
        help="Limit to one watchlist row.",
    )
    return parser.parse_args(argv)


if __name__ == "__main__":
    raise SystemExit(main())
