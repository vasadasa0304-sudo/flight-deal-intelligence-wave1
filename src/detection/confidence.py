"""Confidence scoring for Wave1 anomaly candidates."""

from __future__ import annotations

from decimal import Decimal


def compute_confidence(
    baseline_health: str,
    used_fx_conversion: bool,
    tier: str,
    second_strike_confirmed: bool,
) -> Decimal:
    """Compute a numeric confidence score compatible with detected_anomalies."""
    if baseline_health == "GOOD":
        base = Decimal("1.0")
    elif baseline_health == "THIN":
        base = Decimal("0.7")
    elif baseline_health == "OUTLIER_RISK":
        base = Decimal("0.6")
    else:
        base = Decimal("0.0")

    multiplier = Decimal("1.0")
    if used_fx_conversion:
        multiplier *= Decimal("0.8")
    if tier == "PHANTOM_FARE" and not second_strike_confirmed:
        multiplier *= Decimal("0.5")

    return min(Decimal("1.0"), base * multiplier).quantize(Decimal("0.001"))
