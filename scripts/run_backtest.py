"""Run Wave1 backtest — replay or synthetic injection mode.

Usage:
    python scripts/run_backtest.py --mode replay \\
        --start-date 2026-04-01 --end-date 2026-04-30

    python scripts/run_backtest.py --mode synthetic \\
        --start-date 2026-04-01 --end-date 2026-04-30 \\
        --threshold-set LCC_EXPERIMENTAL
"""

from __future__ import annotations

import argparse
from datetime import date

from sqlalchemy.orm import Session

from src.baselines.backtest import run_replay, run_synthetic
from src.config import load_settings
from src.db_helpers import get_engine
from src.detection.thresholds import THRESHOLD_SET_SOW, THRESHOLD_SETS
from src.logging_config import configure_logging


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"Invalid date '{value}'; expected YYYY-MM-DD.")


def main() -> None:
    """Entry point for the Wave1 backtest CLI."""
    configure_logging()

    parser = argparse.ArgumentParser(
        description="Wave1 backtest harness",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--mode",
        choices=["replay", "synthetic"],
        required=True,
        help="replay: replay real observations; synthetic: inject synthetic deals.",
    )
    parser.add_argument(
        "--start-date",
        required=True,
        type=_parse_date,
        metavar="YYYY-MM-DD",
        help="First date of the backtest window (inclusive).",
    )
    parser.add_argument(
        "--end-date",
        required=True,
        type=_parse_date,
        metavar="YYYY-MM-DD",
        help="Last date of the backtest window (inclusive).",
    )
    parser.add_argument(
        "--threshold-set",
        default=THRESHOLD_SET_SOW,
        choices=list(THRESHOLD_SETS.keys()),
        dest="threshold_set",
        help="Detector threshold set to use.",
    )

    args = parser.parse_args()

    if args.start_date > args.end_date:
        parser.error("--start-date must be before or equal to --end-date.")

    settings = load_settings()
    engine = get_engine(settings)

    with Session(engine) as session:
        if args.mode == "replay":
            result = run_replay(
                session,
                start_date=args.start_date,
                end_date=args.end_date,
                threshold_set=args.threshold_set,
            )
            print(
                f"Replay complete: {result.n_observations} observations, "
                f"{result.n_baselines_built} baselines, "
                f"{result.n_anomalies} anomalies detected."
            )
            print(f"  Summary:   {result.summary_path}")
            print(f"  Per-route: {result.per_route_path}")
        else:
            result = run_synthetic(
                session,
                start_date=args.start_date,
                end_date=args.end_date,
                threshold_set=args.threshold_set,
            )
            print(
                f"Synthetic complete: {result.n_injected} injected observations."
            )
            for tier, recall in result.recall_by_tier.items():
                print(f"  {tier}: recall={recall:.3f}")
            print(f"  Metrics: {result.metrics_path}")


if __name__ == "__main__":
    main()
