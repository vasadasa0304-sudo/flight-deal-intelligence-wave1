"""Formatting helpers for Wave1 confirmed fare alerts."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Mapping

_TIER_LABELS = {
    "DEAL": "Deal",
    "FLASH_DEAL": "Flash Deal",
    "PHANTOM_FARE": "Phantom Fare",
}


def format_alert_markdown(alert: Mapping[str, Any]) -> str:
    """Format one confirmed alert as an internal copy/paste Markdown block."""
    tier = str(alert["tier"])
    tier_label = _TIER_LABELS.get(tier, tier.replace("_", " ").title())
    prefix = "(MEMBER ONLY) " if tier == "PHANTOM_FARE" else ""
    native_currency = str(alert["native_currency"])
    display_currency = str(alert["display_currency"])
    fare_native = _decimal(alert["fare_native"])
    fare_display = _decimal(alert["fare_display"])
    baseline_native = _decimal(alert["baseline_price"])
    baseline_display = _display_equivalent(
        baseline_native,
        fare_native,
        fare_display,
    )
    saving_display = _display_equivalent(
        _decimal(alert["absolute_saving"]),
        fare_native,
        fare_display,
    )
    booking = alert.get("booking_link") or f"via {alert['airline_code']} direct"
    valid_window = alert.get("valid_window") or "typically 24-72h"
    notes = alert.get("verification_notes") or ""

    return "\n".join(
        [
            (
                f"{prefix}{tier_label}: {alert['origin']} -> {alert['destination']} "
                f"on {alert['airline_code']}, {alert['cabin']}"
            ),
            (
                f"Fare: {native_currency} {_format_money(fare_native)} "
                f"(~{display_currency} {_format_money(fare_display)})"
            ),
            (
                f"Baseline: {native_currency} {_format_money(baseline_native)} "
                f"(~{display_currency} {_format_money(baseline_display)})"
            ),
            (
                f"Saving: {_format_percent(alert['percent_saving'])}% / "
                f"{display_currency} {_format_money(saving_display)}"
            ),
            f"Booking: {booking}",
            f"Valid: {valid_window}",
            f"Notes: {notes}",
        ]
    )


def format_alert(
    origin: str,
    destination: str,
    tier: str,
    fare_amount: Decimal,
    currency: str,
) -> str:
    """Format a compact internal alert line for legacy callers."""
    return f"{tier}: {origin}-{destination} at {currency} {fare_amount}"


def _display_equivalent(
    native_amount: Decimal,
    fare_native: Decimal,
    fare_display: Decimal,
) -> Decimal:
    if fare_native == 0:
        return native_amount
    return (native_amount * (fare_display / fare_native)).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )


def _decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Invalid decimal value: {value!r}") from exc


def _format_money(value: Decimal) -> str:
    rounded = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if rounded == rounded.to_integral():
        return f"{int(rounded):,}"
    return f"{rounded:,.2f}"


def _format_percent(value: Any) -> str:
    percent = _decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if percent == percent.to_integral():
        return str(int(percent))
    return f"{percent:.2f}"
