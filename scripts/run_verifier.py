"""Run Wave1 anomaly verification."""

from __future__ import annotations

import argparse
import asyncio
from typing import Sequence

from sqlalchemy.orm import Session

from src.clients.amadeus_client import AmadeusClient
from src.clients.duffel_client import DuffelClient
from src.config import load_settings
from src.db_helpers import get_engine
from src.logging_config import configure_logging
from src.verification.verifier import verify_detected_anomalies


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify Wave1 detected anomalies.")
    parser.add_argument("--anomaly-id", type=int, help="Verify one anomaly.")
    parser.add_argument(
        "--tier",
        choices=("DEAL", "FLASH_DEAL", "PHANTOM_FARE"),
        help="Only verify anomalies of this tier.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run verification and roll back status/qa_check changes.",
    )
    return parser.parse_args(argv)


async def _run(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    settings = load_settings()
    configure_logging(settings.log_level)
    engine = get_engine(settings)
    duffel_client = DuffelClient(settings) if settings.duffel_api_key else None
    try:
        async with AmadeusClient(settings) as amadeus_client:
            with Session(engine) as session:
                outcomes = await verify_detected_anomalies(
                    session,
                    amadeus_client,
                    duffel_client=duffel_client,
                    anomaly_id=args.anomaly_id,
                    tier=args.tier,
                )
                if args.dry_run:
                    session.rollback()
                else:
                    session.commit()
        if args.dry_run:
            print("DRY RUN — no changes committed.")
        print(f"Verifier complete: processed={len(outcomes)}")
        for outcome in outcomes:
            print(
                f"  anomaly_id={outcome.anomaly_id} status={outcome.status} "
                f"source={outcome.verification_source} result={outcome.result} "
                f"notes={outcome.notes}"
            )
        return 0
    finally:
        engine.dispose()


def main(argv: Sequence[str] | None = None) -> int:
    return asyncio.run(_run(argv))


if __name__ == "__main__":
    raise SystemExit(main())
