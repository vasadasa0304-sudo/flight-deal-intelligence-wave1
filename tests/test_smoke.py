"""Smoke tests for the Wave1 skeleton."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from src.config import SUPPORTED_CABINS, WAVE1_AIRLINES, WAVE1_HUBS, WAVE1_MVP_CABINS, load_settings
from src.detection.detector import detect_candidate
from src.ingestion.watchlist_loader import load_watchlist_csv


def test_wave1_settings_load() -> None:
    """Default settings must stay locked to Wave1."""
    settings = load_settings()
    assert settings.wave_scope == "WAVE1"
    assert settings.wave1_hubs == WAVE1_HUBS
    assert settings.wave1_airlines == WAVE1_AIRLINES
    assert settings.wave1_mvp_cabins == WAVE1_MVP_CABINS


def test_schema_supported_cabins_include_phase2_values() -> None:
    """The app schema vocabulary must already allow Phase 2 cabin values."""
    assert SUPPORTED_CABINS == ("ECONOMY", "PREMIUM_ECONOMY", "BUSINESS", "FIRST")
    assert WAVE1_MVP_CABINS == ("ECONOMY", "BUSINESS")


def test_watchlist_loader_allows_phase2_cabins_only_when_inactive(tmp_path: Path) -> None:
    """Active Wave1 rows are MVP cabin only; inactive future rows can use Phase 2 cabins."""
    seed_path = tmp_path / "watchlist.csv"
    seed_path.write_text(
        "origin,destination,marketing_carrier,cabin,booking_window_days,is_active\n"
        "IST,DXB,TK,ECONOMY,14,true\n"
        "IST,DXB,TK,FIRST,60,false\n",
        encoding="utf-8",
    )

    frame = load_watchlist_csv(seed_path)

    assert len(frame) == 2


def test_watchlist_loader_rejects_active_phase2_cabins(tmp_path: Path) -> None:
    """Active Wave1 rows cannot use Phase 2 cabin values."""
    seed_path = tmp_path / "watchlist.csv"
    seed_path.write_text(
        "origin,destination,marketing_carrier,cabin,booking_window_days,is_active\n"
        "IST,DXB,TK,FIRST,14,true\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Active Wave1 rows outside MVP cabins"):
        load_watchlist_csv(seed_path)


def test_detector_classifies_wave1_deal() -> None:
    """A fare meeting both Wave1 thresholds should classify."""
    result = detect_candidate(current_amount=Decimal("100"), baseline_amount=Decimal("200"))
    assert result.tier == "Deal"
    assert result.absolute_saving == Decimal("100")
