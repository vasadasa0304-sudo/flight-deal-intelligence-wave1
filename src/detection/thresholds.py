"""Wave1 fare anomaly thresholds."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class Threshold:
    """Dual-metric threshold for one anomaly tier."""

    tier: str
    percent_below_baseline: Decimal
    minimum_absolute_saving: Decimal


WAVE1_THRESHOLDS = (
    Threshold("Phantom Fare", Decimal("75"), Decimal("250")),
    Threshold("Flash Deal", Decimal("60"), Decimal("150")),
    Threshold("Deal", Decimal("40"), Decimal("80")),
)


def classify_by_threshold(
    percent_below_baseline: Decimal,
    absolute_saving: Decimal,
) -> str | None:
    """Classify an anomaly candidate using Wave1 dual-metric thresholds."""
    for threshold in WAVE1_THRESHOLDS:
        if (
            percent_below_baseline >= threshold.percent_below_baseline
            and absolute_saving >= threshold.minimum_absolute_saving
        ):
            return threshold.tier
    return None

