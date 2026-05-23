"""Promote verified Wave1 anomalies and export confirmed alerts."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path
from typing import Sequence

from sqlalchemy.orm import Session

from src.config import load_settings
from src.db_helpers import get_engine
from src.logging_config import configure_logging
from src.reporting.exports import export_ready_alerts, promote_to_alerts


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export Wave1 confirmed alerts.")
    parser.add_argument(
        "--export-dir",
        default="data/exports",
        help="Directory where confirmed_alerts_YYYYMMDD.csv will be written.",
    )
    parser.add_argument(
        "--no-promote",
        action="store_true",
        help="Skip promoting VERIFIED anomalies before exporting READY alerts.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Promote verified anomalies, write CSV, and mark alerts exported."""
    args = _parse_args(argv)
    settings = load_settings()
    configure_logging(settings.log_level)
    engine = get_engine(settings)
    try:
        with Session(engine) as session:
            promoted = 0 if args.no_promote else promote_to_alerts(session)
            result = export_ready_alerts(
                session,
                export_dir=Path(args.export_dir),
                generated_at=datetime.now(UTC),
            )
            session.commit()
        print(
            f"Alerts promoted={promoted} exported={result.row_count} path={result.path}"
        )
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
