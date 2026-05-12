"""Anomaly detector placeholders."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from src.detection.thresholds import classify_by_threshold


@dataclass(frozen=True)
class DetectionResult:
    """Candidate anomaly classification."""

    tier: str | None
    percent_below_baseline: Decimal
    absolute_saving: Decimal


def detect_candidate(current_amount: Decimal, baseline_amount: Decimal) -> DetectionResult:
    """Evaluate a fare against a baseline without persisting anything."""
    if baseline_amount <= 0:
        raise ValueError("Baseline amount must be greater than zero.")

    absolute_saving = baseline_amount - current_amount
    percent_below = (absolute_saving / baseline_amount) * Decimal("100")
    tier = classify_by_threshold(percent_below, absolute_saving)
    return DetectionResult(
        tier=tier,
        percent_below_baseline=percent_below,
        absolute_saving=absolute_saving,
    )

