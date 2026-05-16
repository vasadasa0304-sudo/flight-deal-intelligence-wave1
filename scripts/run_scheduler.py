"""Run the Wave1 scheduler."""

from __future__ import annotations

import argparse
import asyncio
from typing import Sequence

from sqlalchemy.orm import Session

from src.clients.amadeus_client import AmadeusClient
from src.config import load_settings
from src.db_helpers import get_engine
from src.ingestion.poller import load_active_watch_rows, one_pass
from src.ingestion.scheduler import build_scheduler
from src.logging_config import configure_logging


def _dry_run() -> None:
    settings = load_settings()
    configure_logging(settings.log_level)
    engine = get_engine(settings)
    try:
        with Session(engine) as session:
            rows = load_active_watch_rows(session)
        print(f"Dry run: {len(rows)} active watchlist row(s). No API calls made.")
        for row in rows:
            print(
                f"  watch_id={row['watch_id']} route={row['route_id']} "
                f"airline={row['airline_code']} cabin={row['cabin']} "
                f"window={row['booking_window_days']}d"
            )
    finally:
        engine.dispose()


async def _run_once() -> None:
    settings = load_settings()
    configure_logging(settings.log_level)
    engine = get_engine(settings)
    try:
        with Session(engine) as session:
            async with AmadeusClient(settings) as client:
                counters = await one_pass(session, client)
            session.commit()
        print(
            f"One-shot pass complete: attempted={counters.watch_rows_attempted} "
            f"inserted={counters.observations_inserted} duplicates={counters.duplicates} "
            f"parse_errors={counters.parse_errors} requests_failed={counters.requests_failed} "
            f"status={counters.status}"
        )
    finally:
        engine.dispose()


async def _run_scheduler() -> None:
    settings = load_settings()
    configure_logging(settings.log_level)
    scheduler = build_scheduler(settings)
    scheduler.start()
    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Wave1 fare scheduler.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--dry-run",
        action="store_true",
        help="Print active watchlist rows without calling Amadeus.",
    )
    group.add_argument(
        "--once",
        action="store_true",
        help="Run one polling pass then exit.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    """Start the Wave1 scheduler process."""
    args = _parse_args(argv)
    if args.dry_run:
        _dry_run()
    elif args.once:
        asyncio.run(_run_once())
    else:
        asyncio.run(_run_scheduler())


if __name__ == "__main__":
    main()
