"""Tests for detector confidence scoring."""

from __future__ import annotations

from decimal import Decimal

from src.detection.confidence import compute_confidence


def test_confidence_good_baseline_standard_deal() -> None:
    assert compute_confidence("GOOD", False, "DEAL", False) == Decimal("1.000")


def test_confidence_thin_baseline() -> None:
    assert compute_confidence("THIN", False, "DEAL", False) == Decimal("0.700")


def test_confidence_outlier_risk_baseline() -> None:
    assert compute_confidence("OUTLIER_RISK", False, "DEAL", False) == Decimal("0.600")


def test_confidence_missing_baseline_safety_branch() -> None:
    assert compute_confidence("MISSING", False, "DEAL", False) == Decimal("0.000")


def test_confidence_fx_conversion_penalty() -> None:
    assert compute_confidence("GOOD", True, "DEAL", False) == Decimal("0.800")


def test_confidence_phantom_without_second_strike_penalty() -> None:
    assert compute_confidence("GOOD", False, "PHANTOM_FARE", False) == Decimal("0.500")


def test_confidence_phantom_with_second_strike_confirmed() -> None:
    assert compute_confidence("GOOD", False, "PHANTOM_FARE", True) == Decimal("1.000")
