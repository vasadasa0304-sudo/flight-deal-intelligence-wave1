"""Currency helpers."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP


def quantize_money(amount: Decimal) -> Decimal:
    """Round a monetary amount to two decimal places."""
    return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

