"""Seed default Wave1 API provider budgets."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
import logging

from sqlalchemy import text
from sqlalchemy.orm import Session

from src.config import load_settings
from src.db_helpers import get_engine
from src.logging_config import configure_logging

logger = logging.getLogger(__name__)

DEFAULT_BUDGETS = (
    {
        "provider": "AMADEUS_TEST",
        "daily_call_soft_limit": 1500,
        "daily_call_hard_limit": 2000,
        "cost_soft_limit_usd": Decimal("0.00"),
        "cost_hard_limit_usd": Decimal("0.00"),
    },
    {
        "provider": "AMADEUS",
        "daily_call_soft_limit": 8000,
        "daily_call_hard_limit": 10000,
        "cost_soft_limit_usd": Decimal("10.00"),
        "cost_hard_limit_usd": Decimal("15.00"),
    },
    {
        "provider": "DUFFEL",
        "daily_call_soft_limit": 1000,
        "daily_call_hard_limit": 2000,
        "cost_soft_limit_usd": Decimal("5.00"),
        "cost_hard_limit_usd": Decimal("10.00"),
    },
    {
        "provider": "FX_FRANKFURTER",
        "daily_call_soft_limit": 200,
        "daily_call_hard_limit": 500,
        "cost_soft_limit_usd": Decimal("0.00"),
        "cost_hard_limit_usd": Decimal("0.00"),
    },
)


def main(_argv: Sequence[str] | None = None) -> int:
    """Upsert default provider budgets."""
    settings = load_settings()
    configure_logging(settings.log_level)
    engine = get_engine(settings)
    try:
        with Session(engine) as session:
            session.execute(
                text(
                    """
                    INSERT INTO provider_budgets (
                        provider, daily_call_soft_limit, daily_call_hard_limit,
                        cost_soft_limit_usd, cost_hard_limit_usd, updated_at
                    )
                    VALUES (
                        :provider, :daily_call_soft_limit, :daily_call_hard_limit,
                        :cost_soft_limit_usd, :cost_hard_limit_usd, now()
                    )
                    ON CONFLICT (provider) DO UPDATE SET
                        daily_call_soft_limit = EXCLUDED.daily_call_soft_limit,
                        daily_call_hard_limit = EXCLUDED.daily_call_hard_limit,
                        cost_soft_limit_usd = EXCLUDED.cost_soft_limit_usd,
                        cost_hard_limit_usd = EXCLUDED.cost_hard_limit_usd,
                        updated_at = now()
                    """
                ),
                list(DEFAULT_BUDGETS),
            )
            session.commit()
    finally:
        engine.dispose()
    logger.info("Provider budgets seeded: %d", len(DEFAULT_BUDGETS))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
