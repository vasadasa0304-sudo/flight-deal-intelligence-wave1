"""Baseline health classification for Wave1."""

from __future__ import annotations

from decimal import Decimal


def classify_health(
    observation_count: int,
    iqr_price_native: Decimal,
    median_price_native: Decimal,
) -> str:
    """Return the baseline_health label for one baseline row.

    Priority order checked top-to-bottom:
      1. MISSING       — count < 10; too few data points to be useful
      2. OUTLIER_RISK  — count >= 10 and IQR > 50% of median; high dispersion
      3. GOOD          — count >= 30; sufficient and stable
      4. THIN          — 10 <= count < 30; usable but watch for revision
    """
    if observation_count < 10:
        return "MISSING"
    if median_price_native > 0 and iqr_price_native > Decimal("0.5") * median_price_native:
        return "OUTLIER_RISK"
    if observation_count >= 30:
        return "GOOD"
    return "THIN"
