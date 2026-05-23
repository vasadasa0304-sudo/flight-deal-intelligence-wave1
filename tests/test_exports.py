"""Tests for confirmed alert promotion and CSV export."""

from __future__ import annotations

import csv
import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from src.reporting.exports import ALERT_EXPORT_COLUMNS, export_ready_alerts, promote_to_alerts


@pytest.fixture()
def export_engine(pg_schema_engine: tuple[Engine, str]) -> Iterator[Engine]:
    engine, _schema_name = pg_schema_engine
    _clear_rows(engine)
    _seed_reference_rows(engine)
    try:
        yield engine
    finally:
        _clear_rows(engine)


def test_promote_to_alerts_copies_right_fields(export_engine: Engine) -> None:
    anomaly_id = _insert_anomaly(
        export_engine,
        tier="FLASH_DEAL",
        status="VERIFIED",
        current_price=Decimal("120.00"),
        display_price=Decimal("120.00"),
        absolute_saving=Decimal("180.00"),
        percent_saving=Decimal("60.00"),
        deeplink="https://example.test/book",
    )
    _insert_confirmed_qa(export_engine, anomaly_id, "fare verified")

    with Session(export_engine) as session:
        assert promote_to_alerts(session) == 1
        session.commit()

    alert = _alert(export_engine, anomaly_id)
    assert alert["tier"] == "FLASH_DEAL"
    assert alert["origin"] == "IST"
    assert alert["destination"] == "DXB"
    assert alert["airline_code"] == "TK"
    assert alert["cabin"] == "ECONOMY"
    assert alert["fare_native"] == Decimal("120.00")
    assert alert["fare_display"] == Decimal("120.00")
    assert alert["urgency_flag"] == "HIGH"
    assert alert["visibility"] == "FREE"
    assert alert["verification_notes"] == "fare verified"
    assert _anomaly_status(export_engine, anomaly_id) == "EXPORTED"


def test_phantom_fare_alerts_have_member_visibility(export_engine: Engine) -> None:
    anomaly_id = _insert_anomaly(
        export_engine,
        tier="PHANTOM_FARE",
        status="VERIFIED",
        current_price=Decimal("100.00"),
        absolute_saving=Decimal("300.00"),
        percent_saving=Decimal("75.00"),
    )

    with Session(export_engine) as session:
        assert promote_to_alerts(session) == 1
        session.commit()

    alert = _alert(export_engine, anomaly_id)
    assert alert["visibility"] == "MEMBER"
    assert alert["urgency_flag"] == "URGENT"


def test_csv_writer_emits_expected_columns_and_row_count(
    export_engine: Engine,
    tmp_path: Path,
) -> None:
    anomaly_id = _insert_anomaly(export_engine, tier="DEAL", status="VERIFIED")
    with Session(export_engine) as session:
        promote_to_alerts(session)
        result = export_ready_alerts(session, tmp_path, generated_at=datetime.now(UTC))
        session.commit()

    with result.path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    assert result.row_count == 1
    assert list(rows[0]) == ALERT_EXPORT_COLUMNS
    assert rows[0]["tier"] == "DEAL"
    assert _alert_status(export_engine, anomaly_id) == "EXPORTED"


def test_export_alerts_does_not_export_same_alert_twice(
    export_engine: Engine,
    tmp_path: Path,
) -> None:
    _insert_anomaly(export_engine, tier="DEAL", status="VERIFIED")

    with Session(export_engine) as session:
        promote_to_alerts(session)
        first = export_ready_alerts(session, tmp_path, generated_at=datetime.now(UTC))
        second = export_ready_alerts(session, tmp_path, generated_at=datetime.now(UTC))
        session.commit()

    assert first.row_count == 1
    assert second.row_count == 0


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
    tier: str,
    status: str,
    current_price: Decimal = Decimal("120.00"),
    display_price: Decimal = Decimal("120.00"),
    absolute_saving: Decimal = Decimal("80.00"),
    percent_saving: Decimal = Decimal("40.00"),
    deeplink: str | None = None,
) -> int:
    observed_at = datetime.now(UTC).replace(microsecond=0)
    with engine.begin() as connection:
        obs_id = int(
            connection.execute(
                text(
                    """
                    INSERT INTO price_observations (
                        watch_id, route_id, origin, destination, airline_code,
                        cabin, booking_window_days, departure_date, native_currency,
                        native_price, display_currency, display_price, fx_rate_used,
                        source, deeplink, request_hash, polling_bucket_hour,
                        observed_at, raw_response
                    )
                    VALUES (
                        1, 'IST-DXB', 'IST', 'DXB', 'TK',
                        'ECONOMY', 60, :departure_date, 'USD',
                        :current_price, 'USD', :display_price, 1,
                        'AMADEUS', :deeplink, :request_hash, :bucket,
                        :observed_at, CAST(:raw_response AS jsonb)
                    )
                    RETURNING id
                    """
                ),
                {
                    "departure_date": date(2026, 7, 16),
                    "current_price": current_price,
                    "display_price": display_price,
                    "deeplink": deeplink,
                    "request_hash": f"exports-{uuid.uuid4().hex}",
                    "bucket": observed_at.replace(minute=0, second=0),
                    "observed_at": observed_at,
                    "raw_response": "{}",
                },
            ).scalar_one()
        )
        baseline_id = _insert_baseline(connection, observed_at.date())
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
                        :tier, :current_price, 200.00, 'USD',
                        :absolute_saving, :percent_saving, 0.900,
                        'test anomaly', 'SOW', :status, :detected_at
                    )
                    RETURNING id
                    """
                ),
                {
                    "obs_id": obs_id,
                    "baseline_id": baseline_id,
                    "tier": tier,
                    "current_price": current_price,
                    "absolute_saving": absolute_saving,
                    "percent_saving": percent_saving,
                    "status": status,
                    "detected_at": observed_at,
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
                    200.00, 180.00, 250.00, 190.00, 220.00, 30.00,
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


def _insert_confirmed_qa(engine: Engine, anomaly_id: int, notes: str) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO qa_checks (
                    anomaly_id, verification_source, result, notes, checked_by
                )
                VALUES (:anomaly_id, 'AMADEUS_PRICE', 'CONFIRMED', :notes, 'test')
                """
            ),
            {"anomaly_id": anomaly_id, "notes": notes},
        )


def _alert(engine: Engine, anomaly_id: int) -> dict:
    with engine.connect() as connection:
        row = connection.execute(
            text("SELECT * FROM alerts WHERE anomaly_id = :anomaly_id"),
            {"anomaly_id": anomaly_id},
        ).one()
        return dict(row._mapping)


def _anomaly_status(engine: Engine, anomaly_id: int) -> str:
    with engine.connect() as connection:
        return str(
            connection.execute(
                text("SELECT status FROM detected_anomalies WHERE id = :id"),
                {"id": anomaly_id},
            ).scalar_one()
        )


def _alert_status(engine: Engine, anomaly_id: int) -> str:
    with engine.connect() as connection:
        return str(
            connection.execute(
                text("SELECT status FROM alerts WHERE anomaly_id = :id"),
                {"id": anomaly_id},
            ).scalar_one()
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
