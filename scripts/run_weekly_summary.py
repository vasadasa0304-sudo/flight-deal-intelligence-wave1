"""Write the Wave1 weekly reporting summary."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path
from typing import Sequence

from sqlalchemy.orm import Session

from src.config import load_settings
from src.db_helpers import get_engine
from src.logging_config import configure_logging
from src.reporting.weekly_summary import write_weekly_summary


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Write Wave1 weekly summary exports.")
    parser.add_argument(
        "--export-dir",
        default="data/exports",
        help="Directory where weekly_summary_YYYYMMDD files will be written.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Write weekly Markdown and CSV summary files."""
    args = _parse_args(argv)
    settings = load_settings()
    configure_logging(settings.log_level)
    engine = get_engine(settings)
    try:
        with Session(engine) as session:
            result = write_weekly_summary(
                session,
                export_dir=Path(args.export_dir),
                generated_at=datetime.now(UTC),
            )
        print(f"Weekly summary written: {result.markdown_path} {result.csv_path}")
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
