"""Tests for Wave1 polling orchestration."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from src.ingestion.poller import (
    _run_status,
    load_active_watch_rows,
    one_pass,
)


# ---------------------------------------------------------------------------
# Fake Amadeus client
# ---------------------------------------------------------------------------


class _FakeAmadeusClient:
    """Minimal async client stub — returns a fixed offer list per call."""

    def __init__(self, offers: list[dict[str, Any]]) -> None:
        self._offers = offers

    async def search_flight_offers(self, **_: Any) -> list[dict[str, Any]]:
        return list(self._offers)

    async def __aenter__(self) -> "_FakeAmadeusClient":
        return self

    async def __aexit__(self, *_: Any) -> None:
        pass


# ---------------------------------------------------------------------------
# DB fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def seeded_engine(pg_schema_engine: tuple[Engine, str]) -> Iterator[Engine]:
    engine, _ = pg_schema_engine
    _clear(engine)
    _seed(engine)
    try:
        yield engine
    finally:
        _clear(engine)


# ---------------------------------------------------------------------------
# Unit tests (no database)
# ---------------------------------------------------------------------------


def test_run_status_all_failed_returns_failed() -> None:
    assert _run_status(attempted=3, requests_failed=3) == "FAILED"


def test_run_status_partial_returns_partial() -> None:
    assert _run_status(attempted=3, requests_failed=1) == "PARTIAL"


def test_run_status_all_success_returns_success() -> None:
    assert _run_status(attempted=3, requests_failed=0) == "SUCCESS"


def test_run_status_zero_attempted_returns_success() -> None:
    assert _run_status(attempted=0, requests_failed=0) == "SUCCESS"


# ---------------------------------------------------------------------------
# DB-backed tests
# ---------------------------------------------------------------------------


def test_load_active_watch_rows_returns_seeded_row(seeded_engine: Engine) -> None:
    with Session(seeded_engine) as session:
        rows = load_active_watch_rows(session)

    assert len(rows) == 1
    row = rows[0]
    assert row["route_id"] == "IST-DXB"
    assert row["airline_code"] == "TK"
    assert row["origin"] == "IST"
    assert row["destination"] == "DXB"
    assert row["cabin"] == "ECONOMY"
    assert row["booking_window_days"] == 14


def test_load_active_watch_rows_excludes_inactive_rows(seeded_engine: Engine) -> None:
    with seeded_engine.begin() as connection:
        connection.exec_driver_sql("UPDATE watchlist SET is_active = FALSE")

    with Session(seeded_engine) as session:
        rows = load_active_watch_rows(session)

    assert rows == []


@pytest.mark.asyncio
async def test_one_pass_inserts_observation_and_writes_scheduler_run(
    seeded_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DISPLAY_CURRENCY", "USD")
    client = _FakeAmadeusClient([_offer()])

    with Session(seeded_engine) as session:
        counters = await one_pass(session, client)
        session.commit()

    assert counters.watch_rows_attempted == 1
    assert counters.observations_inserted == 1
    assert counters.duplicates == 0
    assert counters.parse_errors == 0
    assert counters.requests_failed == 0
    assert counters.status == "SUCCESS"

    with seeded_engine.connect() as connection:
        obs_count = connection.execute(
            text("SELECT count(*) FROM price_observations")
        ).scalar_one()
        run_row = connection.execute(
            text("SELECT * FROM scheduler_runs ORDER BY started_at DESC LIMIT 1")
        ).one()

    assert obs_count == 1
    assert run_row.status == "SUCCESS"
    assert run_row.watch_rows_attempted == 1
    assert run_row.observations_inserted == 1
    assert run_row.requests_failed == 0


@pytest.mark.asyncio
async def test_one_pass_counts_duplicate_on_second_call_same_hour(
    seeded_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DISPLAY_CURRENCY", "USD")
    client = _FakeAmadeusClient([_offer()])

    with Session(seeded_engine) as session:
        first = await one_pass(session, client)
        session.commit()

    with Session(seeded_engine) as session:
        second = await one_pass(session, client)
        session.commit()

    assert first.observations_inserted == 1
    assert second.duplicates == 1
    assert second.observations_inserted == 0


@pytest.mark.asyncio
async def test_one_pass_parse_error_when_no_matching_airline(
    seeded_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DISPLAY_CURRENCY", "USD")
    wrong_airline = {**_offer(), "validatingAirlineCodes": ["EK"]}
    client = _FakeAmadeusClient([wrong_airline])

    with Session(seeded_engine) as session:
        counters = await one_pass(session, client)
        session.commit()

    assert counters.parse_errors == 1
    assert counters.observations_inserted == 0
    assert counters.status == "SUCCESS"


@pytest.mark.asyncio
async def test_one_pass_parse_error_when_offer_list_empty(
    seeded_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DISPLAY_CURRENCY", "USD")
    client = _FakeAmadeusClient([])

    with Session(seeded_engine) as session:
        counters = await one_pass(session, client)
        session.commit()

    assert counters.parse_errors == 1
    assert counters.observations_inserted == 0
    assert counters.status == "SUCCESS"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _offer() -> dict[str, Any]:
    """Minimal Amadeus offer matching the seeded IST-DXB / TK / ECONOMY row."""
    return {
        "id": "1",
        "validatingAirlineCodes": ["TK"],
        "price": {"grandTotal": "199.00", "base": "174.00", "currency": "USD"},
        "itineraries": [
            {
                "segments": [
                    {
                        "departure": {"at": "2026-07-15T08:00:00"},
                        "carrierCode": "TK",
                        "numberOfStops": 0,
                    }
                ]
            }
        ],
    }


def _seed(engine: Engine) -> None:
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
            INSERT INTO airlines (
                airline_code, airline_name, carrier_type, primary_hub, is_wave1_airline
            )
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
                route_id, airline_code, cabin, booking_window_days,
                currency, poll_frequency_minutes, route_priority, strategic_tag
            )
            VALUES (
                'IST-DXB', 'TK', 'ECONOMY', 14,
                'USD', 120, 'STANDARD', 'STANDARD'
            )
            """
        )


def _clear(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.exec_driver_sql(
            """
            TRUNCATE TABLE scheduler_runs, price_observations, watchlist,
                           route_carriers, routes, airlines, airports
            RESTART IDENTITY CASCADE
            """
        )
