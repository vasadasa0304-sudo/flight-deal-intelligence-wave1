"""Hashing helpers."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from typing import Any


def stable_payload_hash(payload: dict[str, Any]) -> str:
    """Build a stable SHA-256 hash for dedupe and audit references."""
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def make_request_hash(
    provider: str,
    route_id: str,
    watch_id: int,
    airline_code: str,
    cabin: str,
    departure_date: date,
    booking_window_days: int,
    polling_bucket_hour: datetime,
) -> str:
    """Build the price_observations dedupe key hash."""
    key = "|".join(
        [
            provider,
            route_id,
            str(watch_id),
            airline_code,
            cabin,
            departure_date.isoformat(),
            str(booking_window_days),
            polling_bucket_hour.isoformat(),
        ]
    )
    return hashlib.sha256(key.encode("utf-8")).hexdigest()
