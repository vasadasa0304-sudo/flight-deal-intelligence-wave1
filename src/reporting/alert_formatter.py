"""Alert formatting placeholders."""

from __future__ import annotations

from decimal import Decimal


def format_alert(
    origin: str,
    destination: str,
    tier: str,
    fare_amount: Decimal,
    currency: str,
) -> str:
    """Format a minimal internal alert line."""
    return f"{tier}: {origin}-{destination} at {currency} {fare_amount}"

