"""Tests for append-only price observation writes."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from src.ingestion.observation_writer import insert_observation
from src.utils.hashing import make_request_hash


@pytest.fixture()
def observation_engine(pg_schema_engine: tuple[Engine, str]) -> Iterator[Engine]:
    engine, _schema_name = pg_schema_engine
    _clear_reference_rows(engine)
    _seed_reference_rows(engine)
    try:
        yield engine
    finally:
        _clear_reference_rows(engine)


def test_first_insert_succeeds(observation_engine: Engine) -> None:
    observation = _observation()

    with Session(observation_engine) as session:
        assert insert_observation(session, observation) is True
        session.commit()

    assert _observation_count(observation_engine) == 1


def test_duplicate_request_hash_and_bucket_returns_false(observation_engine: Engine) -> None:
    observation = _observation()

    with Session(observation_engine) as session:
        assert insert_observation(session, observation) is True
        assert insert_observation(session, observation) is False
        session.commit()

    assert _observation_count(observation_engine) == 1


def test_same_request_hash_next_hour_bucket_succeeds(observation_engine: Engine) -> None:
    observation = _observation()
    next_hour = {
        **observation,
        "polling_bucket_hour": observation["polling_bucket_hour"] + timedelta(hours=1),
        "observed_at": observation["observed_at"] + timedelta(hours=1),
    }

    with Session(observation_engine) as session:
        assert insert_observation(session, observation) is True
        assert insert_observation(session, next_hour) is True
        session.commit()

    assert _observation_count(observation_engine) == 2


def _observation() -> dict:
    polling_bucket_hour = datetime(2026, 5, 16, 10, tzinfo=UTC)
    departure_date = date(2026, 7, 15)
    request_hash = make_request_hash(
        provider="AMADEUS",
        route_id="IST-DXB",
        watch_id=1,
        airline_code="TK",
        cabin="ECONOMY",
        departure_date=departure_date,
        booking_window_days=60,
        polling_bucket_hour=polling_bucket_hour,
    )
    return {
        "watch_id": 1,
        "route_id": "IST-DXB",
        "origin": "IST",
        "destination": "DXB",
        "airline_code": "TK",
        "cabin": "ECONOMY",
        "booking_window_days": 60,
        "departure_date": departure_date,
        "return_date": None,
        "native_currency": "USD",
        "native_price": Decimal("199.00"),
        "taxes_fees": Decimal("25.00"),
        "display_currency": "USD",
        "display_price": Decimal("199.00"),
        "fx_rate_used": Decimal("1"),
        "source": "AMADEUS",
        "deeplink": None,
        "request_hash": request_hash,
        "polling_bucket_hour": polling_bucket_hour,
        "observed_at": datetime(2026, 5, 16, 10, 5, tzinfo=UTC),
        "raw_response": {"id": "fixture-offer"},
    }


def _seed_reference_rows(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.exec_driver_sql(
            """
            INSERT INTO airports (airport_code, city, country, region, timezone, is_wave1_hub)
            VALUES
                ('IST', 'Istanbul', 'Turkey', 'Middle East + Turkey', 'Europe/Istanbul', true),
                ('DXB', 'Dubai', 'United Arab Emirates', 'Middle East + Turkey', 'Asia/Dubai', true)
            """
        )
        connection.exec_driver_sql(
            """
            INSERT INTO airlines (airline_code, airline_name, carrier_type, primary_hub, is_wave1_airline)
            VALUES ('TK', 'Turkish Airlines', 'FSC', 'IST', true)
            """
        )
        connection.exec_driver_sql(
            """
            INSERT INTO routes (
                route_id, origin, destination, route_type, route_priority,
                strategic_tag, source_document_note
            )
            VALUES (
                'IST-DXB', 'IST', 'DXB', 'INTERNATIONAL', 'STANDARD',
                'STANDARD', 'test fixture'
            )
            """
        )
        connection.exec_driver_sql(
            """
            INSERT INTO watchlist (
                watch_id, route_id, airline_code, cabin, booking_window_days,
                currency, poll_frequency_minutes, route_priority, strategic_tag
            )
            VALUES (
                1, 'IST-DXB', 'TK', 'ECONOMY', 60,
                'USD', 120, 'STANDARD', 'STANDARD'
            )
            """
        )


def _clear_reference_rows(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.exec_driver_sql(
            """
            TRUNCATE TABLE price_observations, watchlist, route_carriers, routes, airlines, airports
            RESTART IDENTITY CASCADE
            """
        )


def _observation_count(engine: Engine) -> int:
    with engine.connect() as connection:
        return int(connection.execute(text("SELECT count(*) FROM price_observations")).scalar_one())
