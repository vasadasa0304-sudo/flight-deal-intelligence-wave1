"""Smoke tests for the Wave1 skeleton."""

from __future__ import annotations

from decimal import Decimal

from src.config import WAVE1_AIRLINES, WAVE1_CABINS, WAVE1_HUBS, load_settings
from src.detection.detector import detect_candidate


def test_wave1_settings_load() -> None:
    """Default settings must stay locked to Wave1."""
    settings = load_settings()
    assert settings.wave_scope == "WAVE1"
    assert settings.wave1_hubs == WAVE1_HUBS
    assert settings.wave1_airlines == WAVE1_AIRLINES
    assert settings.wave1_cabins == WAVE1_CABINS


def test_detector_classifies_wave1_deal() -> None:
    """A fare meeting both Wave1 thresholds should classify."""
    result = detect_candidate(current_amount=Decimal("100"), baseline_amount=Decimal("200"))
    assert result.tier == "Deal"
    assert result.absolute_saving == Decimal("100")

