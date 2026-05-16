"""Tests for Amadeus fare-offer parsing."""

from __future__ import annotations

import copy
import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from src.ingestion.parser import parse_offer_payload
from src.utils.hashing import make_request_hash


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "amadeus_flight_offers_sample.json"


def test_valid_response_parses_to_expected_dict(monkeypatch) -> None:
    monkeypatch.setenv("DISPLAY_CURRENCY", "CAD")
    payload = _fixture()["data"][0]
    observed_at = datetime(2026, 5, 16, 10, 22, 13, tzinfo=UTC)

    parsed = parse_offer_payload(payload, _watch_row(), observed_at)

    assert parsed is not None
    assert parsed["watch_id"] == 42
    assert parsed["route_id"] == "YUL-CDG"
    assert parsed["origin"] == "YUL"
    assert parsed["destination"] == "CDG"
    assert parsed["airline_code"] == "AC"
    assert parsed["cabin"] == "ECONOMY"
    assert parsed["booking_window_days"] == 60
    assert parsed["departure_date"] == date(2025, 9, 1)
    assert parsed["return_date"] is None
    assert parsed["native_currency"] == "CAD"
    assert parsed["native_price"] == Decimal("612.50")
    assert parsed["taxes_fees"] == Decimal("122.50")
    assert parsed["display_currency"] == "CAD"
    assert parsed["display_price"] == Decimal("612.50")
    assert parsed["fx_rate_used"] == Decimal("1")
    assert parsed["source"] == "AMADEUS"
    assert parsed["deeplink"] is None
    assert parsed["polling_bucket_hour"] == datetime(2026, 5, 16, 10, tzinfo=UTC)
    assert parsed["observed_at"] == observed_at
    assert parsed["raw_response"] == payload


def test_parser_uses_fx_rate_when_session_is_supplied(
    monkeypatch,
    pg_schema_engine: tuple[Engine, str],
) -> None:
    monkeypatch.setenv("DISPLAY_CURRENCY", "USD")
    engine, _schema_name = pg_schema_engine
    _clear_fx_rates(engine)
    _insert_fx_rate(engine, date(2026, 5, 16), "CAD", "USD", Decimal("0.75000000"))

    with Session(engine) as session:
        parsed = parse_offer_payload(_fixture()["data"][0], _watch_row(), _observed_at(), session)

    assert parsed is not None
    assert parsed["display_currency"] == "USD"
    assert parsed["display_price"] == Decimal("459.38")
    assert parsed["fx_rate_used"] == Decimal("0.75000000")


def test_missing_price_returns_none_without_exception() -> None:
    payload = copy.deepcopy(_fixture()["data"][0])
    payload.pop("price")

    assert parse_offer_payload(payload, _watch_row(), _observed_at()) is None


def test_missing_carrier_returns_none_without_exception() -> None:
    payload = copy.deepcopy(_fixture()["data"][0])
    payload.pop("validatingAirlineCodes")
    payload["itineraries"][0]["segments"][0].pop("carrierCode")

    assert parse_offer_payload(payload, _watch_row(), _observed_at()) is None


def test_multiple_offers_mixed_carriers_picks_cheapest_matching_validating_airline() -> None:
    parsed = parse_offer_payload(_fixture(), _watch_row(airline_code="BA"), _observed_at())

    assert parsed is not None
    assert parsed["airline_code"] == "BA"
    assert parsed["native_price"] == Decimal("500.00")
    assert parsed["raw_response"]["id"] == "2"


def test_direct_offer_is_preferred_over_cheaper_one_stop_offer() -> None:
    parsed = parse_offer_payload(_fixture(), _watch_row(airline_code="AC"), _observed_at())

    assert parsed is not None
    assert parsed["airline_code"] == "AC"
    assert parsed["native_price"] == Decimal("612.50")
    assert parsed["raw_response"]["id"] == "1"


def test_request_hash_is_deterministic_and_changes_with_inputs() -> None:
    bucket = datetime(2026, 5, 16, 10, tzinfo=UTC)
    base = {
        "provider": "AMADEUS",
        "route_id": "YUL-CDG",
        "watch_id": 42,
        "airline_code": "AC",
        "cabin": "ECONOMY",
        "departure_date": date(2025, 9, 1),
        "booking_window_days": 60,
        "polling_bucket_hour": bucket,
    }

    first = make_request_hash(**base)
    second = make_request_hash(**base)
    changed = make_request_hash(**{**base, "polling_bucket_hour": bucket + timedelta(hours=1)})

    assert first == second
    assert first != changed
    for key, value in base.items():
        if key == "polling_bucket_hour":
            continue
        variant = {**base, key: _different_value(key, value)}
        assert make_request_hash(**variant) != first


def _fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _watch_row(airline_code: str = "AC") -> dict:
    return {
        "watch_id": 42,
        "route_id": "YUL-CDG",
        "airline_code": airline_code,
        "cabin": "ECONOMY",
        "booking_window_days": 60,
    }


def _observed_at() -> datetime:
    return datetime(2026, 5, 16, 10, 22, 13, tzinfo=UTC)


def _different_value(key: str, value):
    if key == "provider":
        return "DUFFEL"
    if key == "route_id":
        return "YUL-LHR"
    if key == "watch_id":
        return 43
    if key == "airline_code":
        return "BA"
    if key == "cabin":
        return "BUSINESS"
    if key == "departure_date":
        return value + timedelta(days=1)
    if key == "booking_window_days":
        return 14
    raise AssertionError(f"Unhandled key: {key}")


def _insert_fx_rate(
    engine: Engine,
    rate_date: date,
    from_currency: str,
    to_currency: str,
    rate: Decimal,
) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO fx_rates (rate_date, from_currency, to_currency, rate, source)
                VALUES (:rate_date, :from_currency, :to_currency, :rate, 'FRANKFURTER')
                """
            ),
            {
                "rate_date": rate_date,
                "from_currency": from_currency,
                "to_currency": to_currency,
                "rate": rate,
            },
        )


def _clear_fx_rates(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.exec_driver_sql("TRUNCATE TABLE fx_rates")
