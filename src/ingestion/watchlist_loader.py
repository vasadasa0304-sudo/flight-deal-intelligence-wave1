"""Load Wave1 watchlist seed files."""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from src.config import WAVE1_AIRLINES, WAVE1_CABINS, WAVE1_HUBS

logger = logging.getLogger(__name__)


REQUIRED_COLUMNS = {
    "origin",
    "destination",
    "marketing_carrier",
    "cabin",
    "booking_window_days",
}


def load_watchlist_csv(path: Path) -> pd.DataFrame:
    """Load and validate a Wave1 watchlist CSV without writing to the database."""
    logger.info("Loading watchlist seed file: %s", path)
    frame = pd.read_csv(path)
    missing_columns = REQUIRED_COLUMNS - set(frame.columns)
    if missing_columns:
        raise ValueError(f"Missing watchlist columns: {sorted(missing_columns)}")
    _validate_wave1_frame(frame)
    return frame


def _validate_wave1_frame(frame: pd.DataFrame) -> None:
    invalid_origins = set(frame["origin"]) - set(WAVE1_HUBS)
    invalid_carriers = set(frame["marketing_carrier"]) - set(WAVE1_AIRLINES)
    invalid_cabins = set(frame["cabin"]) - set(WAVE1_CABINS)
    if invalid_origins:
        raise ValueError(f"Origins outside Wave1 hubs: {sorted(invalid_origins)}")
    if invalid_carriers:
        raise ValueError(f"Carriers outside Wave1 airlines: {sorted(invalid_carriers)}")
    if invalid_cabins:
        raise ValueError(f"Cabins outside Wave1 MVP cabins: {sorted(invalid_cabins)}")

