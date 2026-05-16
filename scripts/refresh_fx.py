"""Refresh Wave1 FX reference rates."""

from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Sequence

from sqlalchemy import text
from sqlalchemy.engine import Connection

from src.clients.fx_client import FX_PROVIDER_FRANKFURTER, FxClient
from src.config import load_settings
from src.db_helpers import get_engine
from src.logging_config import configure_logging

logger = logging.getLogger(__name__)

WAVE1_BASE_CURRENCIES = ("TRY", "AED", "QAR", "SAR", "EGP")
QUOTE_CURRENCIES = ("USD", "EUR", "GBP")


async def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint."""
    configure_logging()
    args = _parse_args(argv)
    target_date = args.rate_date or datetime.now(UTC).date()
    dates = [target_date - timedelta(days=offset) for offset in range(args.backfill)]
    settings = load_settings()
    engine = get_engine(settings)

    try:
        with engine.begin() as connection:
            async with FxClient(db_session=connection) as client:
                inserted = 0
                for rate_date in dates:
                    for base in WAVE1_BASE_CURRENCIES:
                        logger.info("Refreshing FX for %s base=%s", rate_date, base)
                        rates = await client.fetch_for_date(
                            rate_date,
                            base=base,
                            symbols=list(QUOTE_CURRENCIES),
                        )
                        inserted += _upsert_rates(connection, rate_date, base, rates)
    finally:
        engine.dispose()

    print(f"FX rows refreshed: {inserted}")
    return 0


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Refresh Wave1 FX rates.")
    parser.add_argument(
        "--date",
        dest="rate_date",
        type=date.fromisoformat,
        default=None,
        help="Rate date in YYYY-MM-DD format. Defaults to today UTC.",
    )
    parser.add_argument(
        "--backfill",
        type=int,
        default=1,
        help="Number of days to load, counting backward from --date.",
    )
    return parser.parse_args(argv)


def _upsert_rates(
    connection: Connection,
    rate_date: date,
    base: str,
    rates: dict[str, Decimal],
) -> int:
    if not rates:
        return 0

    rows = [
        {
            "rate_date": rate_date,
            "from_currency": base.upper(),
            "to_currency": quote.upper(),
            "rate": rate,
            "source": FX_PROVIDER_FRANKFURTER,
        }
        for quote, rate in rates.items()
    ]
    connection.execute(
        text(
            """
            INSERT INTO fx_rates (
                rate_date, from_currency, to_currency, rate, source, fetched_at
            )
            VALUES (
                :rate_date, :from_currency, :to_currency, :rate, :source, NOW()
            )
            ON CONFLICT (rate_date, from_currency, to_currency, source)
            DO UPDATE SET
                rate = EXCLUDED.rate,
                fetched_at = NOW()
            """
        ),
        rows,
    )
    return len(rows)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
