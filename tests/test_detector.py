"""Tests for Wave1 anomaly detection."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from src.detection.detector import process_observations


@pytest.fixture()
def detector_engine(pg_schema_engine: tuple[Engine, str]) -> Iterator[Engine]:
    engine, _schema_name = pg_schema_engine
    _clear_rows(engine)
    _seed_reference_rows(engine)
    _insert_fx_rate(engine, "USD", "EUR", Decimal("1.00000000"))
    try:
        yield engine
    finally:
        _clear_rows(engine)


def test_saving_below_deal_threshold_does_not_classify(
    detector_engine: Engine,
) -> None:
    # 7% saving, $14 absolute — both below DEAL thresholds (8% + $25)
    observed_at = _insert_pair(
        detector_engine,
        baseline_price=Decimal("200.00"),
        current_price=Decimal("186.00"),
        currency="EUR",
    )

    _run_detector(detector_engine, observed_at)

    assert _anomalies(detector_engine) == []


def test_saving_above_percent_but_below_absolute_threshold_does_not_classify(
    detector_engine: Engine,
) -> None:
    # 12% saving, $12 absolute — percent above DEAL threshold but absolute below $25
    observed_at = _insert_pair(
        detector_engine,
        baseline_price=Decimal("100.00"),
        current_price=Decimal("88.00"),
        currency="EUR",
    )

    _run_detector(detector_engine, observed_at)

    assert _anomalies(detector_engine) == []


def test_deal_classifies_at_ten_percent_with_absolute_saving(detector_engine: Engine) -> None:
    # 10% saving, $30 absolute — above DEAL (8% + $25) but below FLASH_DEAL (18% + $55)
    observed_at = _insert_pair(
        detector_engine,
        baseline_price=Decimal("300.00"),
        current_price=Decimal("270.00"),
        currency="EUR",
    )

    _run_detector(detector_engine, observed_at)

    rows = _anomalies(detector_engine)
    assert len(rows) == 1
    assert rows[0]["tier"] == "DEAL"
    assert rows[0]["price_observation_id"] is not None
    assert rows[0]["baseline_id"] is not None


def test_flash_deal_classifies_at_twenty_percent_with_absolute_saving(
    detector_engine: Engine,
) -> None:
    # 20% saving, $60 absolute — above FLASH_DEAL (18% + $55) but below PHANTOM_FARE (35% + $120)
    observed_at = _insert_pair(
        detector_engine,
        baseline_price=Decimal("300.00"),
        current_price=Decimal("240.00"),
        currency="EUR",
    )

    _run_detector(detector_engine, observed_at)

    rows = _anomalies(detector_engine)
    assert len(rows) == 1
    assert rows[0]["tier"] == "FLASH_DEAL"


def test_phantom_fare_classifies_at_seventy_five_percent(
    detector_engine: Engine,
) -> None:
    # 75% saving, $300 absolute — above PHANTOM_FARE (35% + $120)
    observed_at = _insert_pair(
        detector_engine,
        baseline_price=Decimal("400.00"),
        current_price=Decimal("100.00"),
        currency="EUR",
    )

    _run_detector(detector_engine, observed_at)

    rows = _anomalies(detector_engine)
    assert len(rows) == 1
    assert rows[0]["tier"] == "PHANTOM_FARE"


def test_missing_baseline_health_does_not_classify(detector_engine: Engine) -> None:
    observed_at = _insert_pair(
        detector_engine,
        baseline_price=Decimal("400.00"),
        current_price=Decimal("100.00"),
        currency="EUR",
        baseline_health="MISSING",
    )

    _run_detector(detector_engine, observed_at)

    assert _anomalies(detector_engine) == []


def test_thin_baseline_classifies_with_confidence_below_one(
    detector_engine: Engine,
) -> None:
    # 10% saving, $30 absolute — DEAL tier; THIN health gives confidence < 1.0
    observed_at = _insert_pair(
        detector_engine,
        baseline_price=Decimal("300.00"),
        current_price=Decimal("270.00"),
        currency="USD",
        baseline_health="THIN",
    )

    _run_detector(detector_engine, observed_at)

    rows = _anomalies(detector_engine)
    assert len(rows) == 1
    assert rows[0]["tier"] == "DEAL"
    assert rows[0]["confidence_score"] < Decimal("1.000")


def test_lcc_threshold_set_requires_45_percent_for_deal(detector_engine: Engine) -> None:
    observed_at = _insert_pair(
        detector_engine,
        baseline_price=Decimal("200.00"),
        current_price=Decimal("112.00"),
        currency="USD",
    )

    _run_detector(detector_engine, observed_at, threshold_set="LCC_EXPERIMENTAL")

    assert _anomalies(detector_engine) == []


def _run_detector(
    engine: Engine,
    observed_at: datetime,
    threshold_set: str = "SOW",
) -> None:
    with Session(engine) as session:
        process_observations(
            session,
            since=observed_at - timedelta(minutes=1),
            threshold_set=threshold_set,
        )
        session.commit()


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


def _insert_pair(
    engine: Engine,
    *,
    baseline_price: Decimal,
    current_price: Decimal,
    currency: str,
    baseline_health: str = "GOOD",
) -> datetime:
    observed_at = datetime.now(UTC).replace(microsecond=0)
    baseline_created_at = observed_at - timedelta(hours=1)
    with engine.begin() as connection:
        connection.execute(
            text(
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
                    1, 'IST-DXB', 'IST', 'DXB', 'TK',
                    'ECONOMY', 60, :departure_date, NULL,
                    :currency, :current_price, NULL,
                    :currency, :current_price, 1,
                    'AMADEUS', NULL, :request_hash, :polling_bucket_hour,
                    :observed_at, CAST(:raw_response AS jsonb)
                )
                """
            ),
            {
                "departure_date": observed_at.date() + timedelta(days=60),
                "currency": currency,
                "current_price": current_price,
                "request_hash": f"test-{uuid4()}",
                "polling_bucket_hour": observed_at.replace(minute=0, second=0),
                "observed_at": observed_at,
                "raw_response": "{}",
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO baselines (
                    watch_id, route_id, origin, destination, airline_code,
                    cabin, booking_window_days, native_currency,
                    baseline_date, window_start_date, window_end_date,
                    median_price_native, min_price_native, max_price_native,
                    p25_price_native, p75_price_native, iqr_price_native,
                    observation_count, baseline_health, created_at
                )
                VALUES (
                    1, 'IST-DXB', 'IST', 'DXB', 'TK',
                    'ECONOMY', 60, :currency,
                    :baseline_date, :window_start_date, :window_end_date,
                    :baseline_price, :baseline_price, :baseline_price,
                    :baseline_price, :baseline_price, 0,
                    40, :baseline_health, :created_at
                )
                """
            ),
            {
                "currency": currency,
                "baseline_date": observed_at.date(),
                "window_start_date": observed_at.date() - timedelta(days=30),
                "window_end_date": observed_at.date() - timedelta(days=1),
                "baseline_price": baseline_price,
                "baseline_health": baseline_health,
                "created_at": baseline_created_at,
            },
        )
    return observed_at


def _insert_fx_rate(
    engine: Engine,
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
                "rate_date": datetime.now(UTC).date(),
                "from_currency": from_currency,
                "to_currency": to_currency,
                "rate": rate,
            },
        )


def _anomalies(engine: Engine) -> list[dict]:
    with engine.connect() as connection:
        result = connection.execute(
            text(
                """
                SELECT
                    price_observation_id, baseline_id, tier,
                    confidence_score, detection_reason
                FROM detected_anomalies
                ORDER BY id
                """
            )
        )
        return [dict(row._mapping) for row in result]


def _clear_rows(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.exec_driver_sql(
            """
            TRUNCATE TABLE
                detected_anomalies, baselines, price_observations, fx_rates,
                watchlist, route_carriers, routes, airlines, airports
            RESTART IDENTITY CASCADE
            """
        )
