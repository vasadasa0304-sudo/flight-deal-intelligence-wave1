"""Tests for Wave1 manual QA and Phantom Fare rules."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from src.verification.qa_rules import (
    missing_qa_fields,
    passes_phantom_two_source_rule,
    required_qa_fields,
)


@pytest.fixture()
def qa_rules_engine(pg_schema_engine: tuple[Engine, str]) -> Iterator[Engine]:
    engine, _schema = pg_schema_engine
    _clear_rows(engine)
    _seed_reference_rows(engine)
    try:
        yield engine
    finally:
        _clear_rows(engine)


def test_required_qa_fields_returns_more_fields_for_phantom_fare() -> None:
    deal_fields = required_qa_fields("DEAL")
    phantom_fields = required_qa_fields("PHANTOM_FARE")

    assert len(phantom_fields) > len(deal_fields)
    assert set(deal_fields) < set(phantom_fields)
    assert "external_verification_documented" in phantom_fields

    review = {field: True for field in deal_fields}
    review["tier"] = "PHANTOM_FARE"
    assert "external_verification_documented" in missing_qa_fields(review)


def test_passes_phantom_two_source_rule_honours_both_api_sources(
    qa_rules_engine: Engine,
) -> None:
    anomaly_id = _insert_anomaly(qa_rules_engine)
    _insert_qa(qa_rules_engine, anomaly_id, source="AMADEUS_PRICE", price=Decimal("100.50"))
    _insert_qa(qa_rules_engine, anomaly_id, source="DUFFEL", price=Decimal("99.00"))

    with Session(qa_rules_engine) as session:
        assert passes_phantom_two_source_rule(anomaly_id, session) is True


def test_passes_phantom_two_source_rule_honours_second_strike_plus_manual(
    qa_rules_engine: Engine,
) -> None:
    first_bucket = datetime(2026, 5, 17, 10, tzinfo=UTC)
    _insert_anomaly(qa_rules_engine, bucket=first_bucket)
    current_id = _insert_anomaly(qa_rules_engine, bucket=first_bucket + timedelta(hours=1))
    _insert_qa(qa_rules_engine, current_id, source="MANUAL", price=None, notes=None)

    with Session(qa_rules_engine) as session:
        assert passes_phantom_two_source_rule(current_id, session) is True


def test_passes_phantom_two_source_rule_honours_manual_external_override(
    qa_rules_engine: Engine,
) -> None:
    anomaly_id = _insert_anomaly(qa_rules_engine)
    _insert_qa(
        qa_rules_engine,
        anomaly_id,
        source="MANUAL",
        price=None,
        notes="Checked via airline site.",
        external_source_verified=True,
    )

    with Session(qa_rules_engine) as session:
        assert passes_phantom_two_source_rule(anomaly_id, session) is True


def test_passes_phantom_two_source_rule_rejects_single_unconfirmed_strike(
    qa_rules_engine: Engine,
) -> None:
    anomaly_id = _insert_anomaly(qa_rules_engine)
    _insert_qa(qa_rules_engine, anomaly_id, source="AMADEUS_PRICE", price=Decimal("100.00"))

    with Session(qa_rules_engine) as session:
        assert passes_phantom_two_source_rule(anomaly_id, session) is False


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


def _insert_anomaly(engine: Engine, bucket: datetime | None = None) -> int:
    bucket = bucket or datetime(2026, 5, 17, 10, tzinfo=UTC)
    request_hash = f"qa-rules-{uuid.uuid4().hex}"
    with engine.begin() as connection:
        obs_id = int(
            connection.execute(
                text(
                    """
                    INSERT INTO price_observations (
                        watch_id, route_id, origin, destination, airline_code,
                        cabin, booking_window_days, departure_date,
                        native_currency, native_price,
                        display_currency, display_price,
                        source, request_hash, polling_bucket_hour,
                        observed_at, raw_response
                    )
                    VALUES (
                        1, 'IST-DXB', 'IST', 'DXB', 'TK',
                        'ECONOMY', 60, :departure_date,
                        'USD', 100.00,
                        'USD', 100.00,
                        'AMADEUS', :request_hash, :bucket,
                        :observed_at, CAST(:raw_response AS jsonb)
                    )
                    RETURNING id
                    """
                ),
                {
                    "departure_date": date(2026, 7, 16),
                    "request_hash": request_hash,
                    "bucket": bucket,
                    "observed_at": bucket + timedelta(minutes=5),
                    "raw_response": '{"id":"fixture-offer","price":{"grandTotal":"100.00","currency":"USD"}}',
                },
            ).scalar_one()
        )
        baseline_id = int(
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
                        :baseline_date, DATE '2026-04-17', DATE '2026-05-16',
                        400.00, 350.00, 500.00, 375.00, 425.00, 50.00,
                        30, 'GOOD'
                    )
                    ON CONFLICT (watch_id, baseline_date) DO UPDATE
                        SET created_at = NOW()
                    RETURNING id
                    """
                ),
                {"baseline_date": bucket.date()},
            ).scalar_one()
        )
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
                        'PHANTOM_FARE', 100.00, 400.00, 'USD',
                        300.00, 75.00, 0.950,
                        'test phantom', 'SOW', 'DETECTED', :detected_at
                    )
                    RETURNING id
                    """
                ),
                {
                    "obs_id": obs_id,
                    "baseline_id": baseline_id,
                    "detected_at": bucket + timedelta(minutes=10),
                },
            ).scalar_one()
        )


def _insert_qa(
    engine: Engine,
    anomaly_id: int,
    *,
    source: str,
    price: Decimal | None,
    notes: str | None = None,
    external_source_verified: bool = False,
) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO qa_checks (
                    anomaly_id, verification_source, verified_price,
                    verified_currency, result, notes, external_source_verified,
                    checked_by
                )
                VALUES (
                    :anomaly_id, :source, :price,
                    CASE WHEN :price IS NULL THEN NULL ELSE 'USD' END,
                    'CONFIRMED', :notes, :external_source_verified, 'test'
                )
                """
            ),
            {
                "anomaly_id": anomaly_id,
                "source": source,
                "price": price,
                "notes": notes,
                "external_source_verified": external_source_verified,
            },
        )


def _clear_rows(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.exec_driver_sql(
            """
            TRUNCATE TABLE
                qa_checks, detected_anomalies, baselines, price_observations,
                watchlist, route_carriers, routes, airlines, airports
            RESTART IDENTITY CASCADE
            """
        )
