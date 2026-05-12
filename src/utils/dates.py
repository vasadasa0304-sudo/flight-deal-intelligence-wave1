"""Date helpers."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta


def utc_now() -> datetime:
    """Return the current UTC timestamp."""
    return datetime.now(tz=UTC)


def departure_date_for_window(start_date: date, booking_window_days: int) -> date:
    """Return the departure date for a booking window."""
    return start_date + timedelta(days=booking_window_days)

