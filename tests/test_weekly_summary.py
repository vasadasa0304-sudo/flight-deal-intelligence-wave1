"""Tests for Wave1 weekly summary reporting."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from src.reporting.weekly_summary import build_weekly_summary


@pytest.fixture()
def weekly_engine(pg_schema_engine: tuple[Engine, str]) -> Iterator[Engine]:
    engine, _schema_name = pg_schema_engine
    _clear_rows(engine)
    _seed_reference_rows(engine)
    try:
        yield engine
    finally:
        _clear_rows(engine)


def test_rejection_rate_denominator_excludes_escalated(weekly_engine: Engine) -> None:
    generated_at = datetime.now(UTC).replace(microsecond=0)
    anomaly_id = _insert_anomaly(
        weekly_engine,
        generated_at=generated_at,
        tier="DEAL",
        absolute_saving=Decimal("80.00"),
    )
    _insert_qa(weekly_engine, anomaly_id, "CONFIRMED", generated_at)
    _insert_qa(weekly_engine, anomaly_id, "REJECTED", generated_at)
    _insert_qa(weekly_engine, anomaly_id, "ESCALATED", generated_at)

    with Session(weekly_engine) as session:
        summary = build_weekly_summary(session, generated_at)

    assert summary.rejection_rate == Decimal("0.500")


def test_top_3_deals_are_ordered_by_absolute_saving_desc(weekly_engine: Engine) -> None:
    generated_at = datetime.now(UTC).replace(microsecond=0)
    _insert_anomaly(weekly_engine, generated_at=generated_at, tier="DEAL", absolute_saving=Decimal("90.00"))
    _insert_anomaly(
        weekly_engine,
        generated_at=generated_at,
        tier="FLASH_DEAL",
        absolute_saving=Decimal("220.00"),
    )
    _insert_anomaly(
        weekly_engine,
        generated_at=generated_at,
        tier="PHANTOM_FARE",
        absolute_saving=Decimal("300.00"),
    )
    _insert_anomaly(weekly_engine, generated_at=generated_at, tier="DEAL", absolute_saving=Decimal("120.00"))

    with Session(weekly_engine) as session:
        summary = build_weekly_summary(session, generated_at)

    assert [deal["absolute_saving_usd"] for deal in summary.top_3_deals] == [
        Decimal("300.00"),
        Decimal("220.00"),
        Decimal("120.00"),
    ]


def test_summary_handles_empty_window_gracefully(weekly_engine: Engine) -> None:
    generated_at = datetime.now(UTC).replace(microsecond=0)

    with Session(weekly_engine) as session:
        summary = build_weekly_summary(session, generated_at)

    assert summary.routes_monitored == 0
    assert summary.observations_collected == 0
    assert summary.anomalies_detected_by_tier == {}
    assert summary.anomalies_confirmed_by_tier == {}
    assert summary.rejection_rate == Decimal("0.000")
    assert summary.top_3_deals == []


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


def _insert_anomaly(
    engine: Engine,
    *,
    generated_at: datetime,
    tier: str,
    absolute_saving: Decimal,
) -> int:
    with engine.begin() as connection:
        obs_id = int(
            connection.execute(
                text(
                    """
                    INSERT INTO price_observations (
                        watch_id, route_id, origin, destination, airline_code,
                        cabin, booking_window_days, departure_date, native_currency,
                        native_price, display_currency, display_price, fx_rate_used,
                        source, request_hash, polling_bucket_hour, observed_at,
                        raw_response
                    )
                    VALUES (
                        1, 'IST-DXB', 'IST', 'DXB', 'TK',
                        'ECONOMY', 60, :departure_date, 'USD',
                        120.00, 'USD', 120.00, 1,
                        'AMADEUS', :request_hash, :bucket, :observed_at,
                        CAST(:raw_response AS jsonb)
                    )
                    RETURNING id
                    """
                ),
                {
                    "departure_date": date(2026, 7, 16),
                    "request_hash": f"weekly-{uuid.uuid4().hex}",
                    "bucket": generated_at.replace(minute=0, second=0),
                    "observed_at": generated_at,
                    "raw_response": "{}",
                },
            ).scalar_one()
        )
        baseline_id = _insert_baseline(connection, generated_at.date())
        return int(
            connection.execute(
                text(
                    """
                    INSERT INTO detected_anomalies (
                        price_observation_id, baseline_id, watch_id,
                        tier, current_price, baseline_price, currency,
                        absolute_saving, percent_saving, confidence_score,
                        detection_reason, threshold_set, status, detected_at
                    )
                    VALUES (
                        :obs_id, :baseline_id, 1,
                        :tier, 120.00, 400.00, 'USD',
                        :absolute_saving, 40.00, 0.900,
                        'test anomaly', 'SOW', 'VERIFIED', :detected_at
                    )
                    RETURNING id
                    """
                ),
                {
                    "obs_id": obs_id,
                    "baseline_id": baseline_id,
                    "tier": tier,
                    "absolute_saving": absolute_saving,
                    "detected_at": generated_at,
                },
            ).scalar_one()
        )


def _insert_baseline(connection, baseline_date: date) -> int:
    return int(
        connection.execute(
            text(
                """
                INSERT INTO baselines (
                    watch_id, route_id, origin, destination, airline_code,
                    cabin, booking_window_days, native_currency,
                    baseline_date, window_start_date, window_end_date,
                    median_price_native, min_price_native, max_price_native,
                    p25_price_native, p75_price_native, iqr_price_native,
                    observation_count, baseline_health
                )
                VALUES (
                    1, 'IST-DXB', 'IST', 'DXB', 'TK',
                    'ECONOMY', 60, 'USD',
                    :baseline_date, :window_start, :window_end,
                    400.00, 350.00, 500.00, 375.00, 425.00, 50.00,
                    40, 'GOOD'
                )
                ON CONFLICT ON CONSTRAINT uq_baselines_watch_date
                DO UPDATE SET created_at = NOW()
                RETURNING id
                """
            ),
            {
                "baseline_date": baseline_date,
                "window_start": baseline_date - timedelta(days=30),
                "window_end": baseline_date - timedelta(days=1),
            },
        ).scalar_one()
    )


def _insert_qa(engine: Engine, anomaly_id: int, result: str, checked_at: datetime) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO qa_checks (
                    anomaly_id, checked_at, verification_source, result
                )
                VALUES (:anomaly_id, :checked_at, 'AMADEUS_PRICE', :result)
                """
            ),
            {
                "anomaly_id": anomaly_id,
                "checked_at": checked_at,
                "result": result,
            },
        )


def _clear_rows(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.exec_driver_sql(
            """
            TRUNCATE TABLE
                alerts, qa_checks, detected_anomalies, baselines, price_observations,
                watchlist, route_carriers, routes, airlines, airports
            RESTART IDENTITY CASCADE
            """
        )
