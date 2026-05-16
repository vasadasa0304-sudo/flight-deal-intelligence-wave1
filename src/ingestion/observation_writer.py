"""Append-only price observation writer."""

from __future__ import annotations

from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB


def insert_observation(session: Any, observation: dict[str, Any]) -> bool:
    """Insert one price observation, returning False for duplicate buckets.

    price_observations is append-only. This function never updates an existing
    row; duplicate (request_hash, polling_bucket_hour) observations are ignored.
    """
    statement = text(
        """
        INSERT INTO price_observations (
            watch_id, route_id, origin, destination, airline_code,
            cabin, booking_window_days, departure_date, return_date,
            native_currency, native_price, taxes_fees,
            display_currency, display_price, fx_rate_used,
            source, deeplink, request_hash, polling_bucket_hour,
            observed_at, raw_response
        )
        VALUES (
            :watch_id, :route_id, :origin, :destination, :airline_code,
            :cabin, :booking_window_days, :departure_date, :return_date,
            :native_currency, :native_price, :taxes_fees,
            :display_currency, :display_price, :fx_rate_used,
            :source, :deeplink, :request_hash, :polling_bucket_hour,
            :observed_at, :raw_response
        )
        ON CONFLICT (request_hash, polling_bucket_hour) DO NOTHING
        RETURNING id
        """
    ).bindparams(bindparam("raw_response", type_=JSONB))

    result = session.execute(statement, observation)
    return result.scalar_one_or_none() is not None
