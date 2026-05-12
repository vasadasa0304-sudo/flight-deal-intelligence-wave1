"""Confidence scoring placeholders."""

from __future__ import annotations

from decimal import Decimal


def assign_confidence(observation_count: int, percent_below_baseline: Decimal) -> str:
    """Assign a simple placeholder confidence label."""
    if observation_count < 30:
        return "low"
    if percent_below_baseline >= Decimal("75"):
        return "needs_heightened_qa"
    return "standard_qa"

