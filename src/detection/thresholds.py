"""Wave1 fare anomaly thresholds."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

THRESHOLD_SET_SOW = "SOW"
THRESHOLD_SET_LCC_EXPERIMENTAL = "LCC_EXPERIMENTAL"


@dataclass(frozen=True)
class Threshold:
    """Dual-metric threshold for one anomaly tier."""

    tier: str
    percent_below_baseline: Decimal
    minimum_absolute_saving: Decimal


SOW_THRESHOLDS = (
    Threshold("PHANTOM_FARE", Decimal("75"), Decimal("250")),
    Threshold("FLASH_DEAL", Decimal("60"), Decimal("150")),
    Threshold("DEAL", Decimal("40"), Decimal("80")),
)

LCC_EXPERIMENTAL_THRESHOLDS = (
    Threshold("PHANTOM_FARE", Decimal("80"), Decimal("250")),
    Threshold("FLASH_DEAL", Decimal("65"), Decimal("150")),
    Threshold("DEAL", Decimal("45"), Decimal("80")),
)

THRESHOLD_SETS = {
    THRESHOLD_SET_SOW: SOW_THRESHOLDS,
    THRESHOLD_SET_LCC_EXPERIMENTAL: LCC_EXPERIMENTAL_THRESHOLDS,
}

# Backwards-compatible alias for existing smoke/currency tests.
WAVE1_THRESHOLDS = SOW_THRESHOLDS


def classify_by_threshold(
    percent_below_baseline: Decimal,
    absolute_saving: Decimal,
    threshold_set: str = THRESHOLD_SET_SOW,
    absolute_thresholds_native: dict[str, Decimal] | None = None,
) -> str | None:
    """Classify an anomaly candidate using Wave1 dual-metric thresholds."""
    thresholds = get_thresholds(threshold_set)
    for threshold in thresholds:
        minimum_absolute_saving = (
            absolute_thresholds_native.get(threshold.tier, threshold.minimum_absolute_saving)
            if absolute_thresholds_native is not None
            else threshold.minimum_absolute_saving
        )
        if (
            percent_below_baseline >= threshold.percent_below_baseline
            and absolute_saving >= minimum_absolute_saving
        ):
            return threshold.tier
    return None


def get_thresholds(threshold_set: str) -> tuple[Threshold, ...]:
    """Return thresholds for a supported detector threshold set."""
    try:
        return THRESHOLD_SETS[threshold_set]
    except KeyError as exc:
        raise ValueError(f"Unsupported threshold_set: {threshold_set}") from exc
