"""Currency helpers for Wave1 fare observations and anomaly logic."""

from __future__ import annotations

import logging
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from sqlalchemy import text

logger = logging.getLogger(__name__)

FX_SOURCE_FRANKFURTER = "FRANKFURTER"
SPECIAL_HANDLING_CURRENCIES = ("EGP", "TRY", "SAR")


def quantize_money(amount: Decimal) -> Decimal:
    """Round a monetary amount to two decimal places."""
    return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def convert_amount(
    amount: Decimal,
    from_currency: str,
    to_currency: str,
    rate_date: date,
    session: Any,
) -> tuple[Decimal, Decimal] | None:
    """Convert money using fx_rates, falling back to the last 7 days."""
    from_code = from_currency.upper()
    to_code = to_currency.upper()
    if from_code == to_code:
        return quantize_money(amount), Decimal("1")

    statement = text(
        """
        SELECT rate
        FROM fx_rates
        WHERE from_currency = :from_currency
          AND to_currency = :to_currency
          AND source = :source
          AND rate_date <= :rate_date
          AND rate_date >= :min_rate_date
        ORDER BY rate_date DESC
        LIMIT 1
        """
    )
    row = session.execute(
        statement,
        {
            "from_currency": from_code,
            "to_currency": to_code,
            "source": FX_SOURCE_FRANKFURTER,
            "rate_date": rate_date,
            "min_rate_date": rate_date - timedelta(days=7),
        },
    ).first()

    if row is None:
        logger.warning(
            "No FX rate found for %s→%s on %s or prior 7 days.",
            from_code,
            to_code,
            rate_date,
        )
        return None

    rate = Decimal(str(row[0]))
    return quantize_money(amount * rate), rate


def native_or_display(
    observation_currency: str,
    baseline_currency: str | None,
) -> str:
    """Return NATIVE if currencies match, else DISPLAY."""
    if baseline_currency and observation_currency.upper() == baseline_currency.upper():
        return "NATIVE"
    return "DISPLAY"


def is_special_handling(currency: str) -> bool:
    """Return True for currencies requiring extra Wave1 FX scrutiny."""
    return currency.upper() in SPECIAL_HANDLING_CURRENCIES
