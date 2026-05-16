"""Run the Wave1 anomaly detector."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
from typing import Sequence

from sqlalchemy.orm import Session

from src.config import load_settings
from src.db_helpers import get_engine
from src.detection.detector import process_observations
from src.detection.thresholds import THRESHOLD_SET_SOW, THRESHOLD_SETS
from src.logging_config import configure_logging


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Wave1 anomaly detection.")
    parser.add_argument(
        "--since",
        help="Process observations observed on or after YYYY-MM-DD UTC.",
    )
    parser.add_argument(
        "--threshold-set",
        choices=tuple(THRESHOLD_SETS),
        default=THRESHOLD_SET_SOW,
        help="Threshold set to use. LCC_EXPERIMENTAL is for backtesting only.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Log classifications without inserting detected_anomalies rows.",
    )
    return parser.parse_args(argv)


def _since_from_args(raw_since: str | None) -> datetime:
    if raw_since is None:
        return datetime.now(UTC) - timedelta(hours=24)
    parsed = datetime.fromisoformat(raw_since)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def main(argv: Sequence[str] | None = None) -> int:
    """Run detector over recent observations."""
    args = _parse_args(argv)
    settings = load_settings()
    configure_logging(settings.log_level)
    engine = get_engine(settings)
    try:
        with Session(engine) as session:
            summary = process_observations(
                session,
                since=_since_from_args(args.since),
                threshold_set=args.threshold_set,
                dry_run=args.dry_run,
            )
            if args.dry_run:
                session.rollback()
            else:
                session.commit()
        print(
            "Detector complete: "
            f"seen={summary.observations_seen} "
            f"classified={summary.classified} "
            f"inserted={summary.inserted} "
            f"skipped={summary.skipped} "
            f"dry_run={summary.dry_run}"
        )
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
