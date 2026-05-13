"""Load Wave1 watchlist seed files.

Validates the CSV column shape expected by the production watchlist table,
then returns a cleaned DataFrame.  Writing to PostgreSQL is the seed
loader script's job (scripts/load_seed_data.py).
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from src.config import WAVE1_AIRLINES, WAVE1_MVP_CABINS

logger = logging.getLogger(__name__)

# Columns the production watchlist CSV must contain.
# Matches the watchlist table grain: route_id, airline_code,
# cabin, booking_window_days, plus the scheduler operational columns.
REQUIRED_COLUMNS = {
    "route_id",
    "airline_code",
    "cabin",
    "booking_window_days",
    "currency",
    "poll_frequency_minutes",
    "route_priority",
    "strategic_tag",
}

VALID_ROUTE_PRIORITIES = {"TIER_1_DAILY", "TIER_2_EVERY_2_DAYS", "STANDARD"}
VALID_STRATEGIC_TAGS = {"STANDARD", "WAVE_2_PRESEED", "WAVE_3_PRESEED"}
VALID_BOOKING_WINDOWS = {14, 60}


def load_watchlist_csv(path: Path) -> pd.DataFrame:
    """Load and validate a Wave1 watchlist CSV without writing to the database.

    Raises ValueError with a descriptive message if validation fails.
    Returns the validated DataFrame on success.
    """
    logger.info("Loading watchlist seed file: %s", path)
    frame = pd.read_csv(path)

    missing_columns = REQUIRED_COLUMNS - set(frame.columns)
    if missing_columns:
        raise ValueError(f"Missing watchlist columns: {sorted(missing_columns)}")

    _validate_wave1_frame(frame)
    return frame


def _validate_wave1_frame(frame: pd.DataFrame) -> None:
    """Run all Wave1 domain validations.  Raises ValueError on the first failure."""
    active_mask = (
        frame["is_active"].fillna(True).astype(bool)
        if "is_active" in frame.columns
        else pd.Series(True, index=frame.index)
    )

    # Airline codes must be in the Wave1 set (active or inactive).
    invalid_carriers = set(frame["airline_code"]) - set(WAVE1_AIRLINES)
    if invalid_carriers:
        raise ValueError(f"Carriers outside Wave1 airlines: {sorted(invalid_carriers)}")

    # Active rows: cabin must be an MVP cabin (ECONOMY / BUSINESS).
    invalid_cabins = set(frame.loc[active_mask, "cabin"]) - set(WAVE1_MVP_CABINS)
    if invalid_cabins:
        raise ValueError(f"Active Wave1 rows outside MVP cabins: {sorted(invalid_cabins)}")

    # booking_window_days must be 14 or 60.
    invalid_windows = (
        set(frame["booking_window_days"].dropna().astype(int)) - VALID_BOOKING_WINDOWS
    )
    if invalid_windows:
        raise ValueError(
            f"booking_window_days must be 14 or 60; found: {sorted(invalid_windows)}"
        )

    # route_priority must be a recognised value.
    if "route_priority" in frame.columns:
        invalid_priorities = set(frame["route_priority"].dropna()) - VALID_ROUTE_PRIORITIES
        if invalid_priorities:
            raise ValueError(f"Invalid route_priority values: {sorted(invalid_priorities)}")

    # strategic_tag must be a recognised value.
    if "strategic_tag" in frame.columns:
        invalid_tags = set(frame["strategic_tag"].dropna()) - VALID_STRATEGIC_TAGS
        if invalid_tags:
            raise ValueError(f"Invalid strategic_tag values: {sorted(invalid_tags)}")

    # poll_frequency_minutes must be positive.
    if "poll_frequency_minutes" in frame.columns:
        freqs = frame["poll_frequency_minutes"].dropna().astype(int)
        if (freqs <= 0).any():
            raise ValueError("poll_frequency_minutes must be > 0 for all rows")

    # route_id must be non-empty.
    blank_route_ids = frame["route_id"].isna() | (frame["route_id"].str.strip() == "")
    if blank_route_ids.any():
        raise ValueError("route_id must be non-empty for every row")

    logger.info(
        "Watchlist validation passed: %d rows (%d active).",
        len(frame),
        int(active_mask.sum()),
    )
