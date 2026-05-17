"""Tests for detected anomaly verification flow."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from src.models import PriceObservation
from src.verification.verifier import verify_detected_anomalies


class FakeAmadeusClient:
    def __init__(self, payload: dict[str, Any] | None) -> None:
        self.payload = payload
        self.calls: list[dict[str, Any]] = []

    async def verify_price(self, original_offer: dict[str, Any]) -> dict[str, Any] | None:
        self.calls.append(original_offer)
        return self.payload


class FakeDuffelClient:
    def __init__(self, payload: dict[str, Any] | None) -> None:
        self.payload = payload
        self.calls: list[dict[str, Any]] = []

    async def verify_offer(self, original_offer: dict[str, Any]) -> dict[str, Any] | None:
        self.calls.append(original_offer)
        return self.payload


@pytest.fixture()
def verifier_engine(pg_schema_engine: tuple[Engine, str]) -> Iterator[Engine]:
    engine, _schema = pg_schema_engine
    _clear_rows(engine)
    _seed_reference_rows(engine)
    try:
        yield engine
    finally:
        _clear_rows(engine)


@pytest.mark.asyncio
async def test_deal_with_amadeus_price_confirmed_becomes_verified(verifier_engine: Engine) -> None:
    anomaly_id = _insert_anomaly(verifier_engine, tier="DEAL", current_price=Decimal("100.00"))

    with Session(verifier_engine) as session:
        await verify_detected_anomalies(session, FakeAmadeusClient(_price_payload("101.00")), anomaly_id=anomaly_id)
        session.commit()

    assert _anomaly_status(verifier_engine, anomaly_id) == "VERIFIED"
    assert _latest_qa(verifier_engine, anomaly_id)["result"] == "CONFIRMED"


@pytest.mark.asyncio
async def test_anomaly_escalated_when_observation_missing(verifier_engine: Engine) -> None:
    anomaly_id = _insert_anomaly(verifier_engine, tier="DEAL", current_price=Decimal("100.00"))

    with Session(verifier_engine) as session:
        # price_observation_id is NOT NULL with a FK so we cannot delete the
        # row directly. Patching session.get is safe here because the fresh
        # session has an empty identity map — no caching risk.
        original_get = session.get

        def fake_get(entity: Any, ident: Any, *args: Any, **kwargs: Any) -> Any:
            if entity is PriceObservation:
                return None
            return original_get(entity, ident, *args, **kwargs)

        session.get = fake_get  # type: ignore[method-assign]
        await verify_detected_anomalies(session, FakeAmadeusClient(_price_payload("100.00")), anomaly_id=anomaly_id)
        session.commit()

    assert _anomaly_status(verifier_engine, anomaly_id) == "ESCALATED"
    qa = _latest_qa(verifier_engine, anomaly_id)
    assert qa["result"] == "ESCALATED"
    assert qa["notes"] == "original offer unavailable"


@pytest.mark.asyncio
async def test_deal_verified_with_nested_flight_offers_payload(verifier_engine: Engine) -> None:
    anomaly_id = _insert_anomaly(verifier_engine, tier="DEAL", current_price=Decimal("200.00"))
    payload = {"flightOffers": [{"price": {"grandTotal": "201.00", "currency": "USD"}}]}

    with Session(verifier_engine) as session:
        await verify_detected_anomalies(session, FakeAmadeusClient(payload), anomaly_id=anomaly_id)
        session.commit()

    assert _anomaly_status(verifier_engine, anomaly_id) == "VERIFIED"
    assert _latest_qa(verifier_engine, anomaly_id)["result"] == "CONFIRMED"


@pytest.mark.asyncio
async def test_deal_with_amadeus_price_rejected_becomes_rejected(verifier_engine: Engine) -> None:
    anomaly_id = _insert_anomaly(verifier_engine, tier="DEAL", current_price=Decimal("100.00"))

    with Session(verifier_engine) as session:
        await verify_detected_anomalies(session, FakeAmadeusClient(_price_payload("106.00")), anomaly_id=anomaly_id)
        session.commit()

    assert _anomaly_status(verifier_engine, anomaly_id) == "REJECTED"
    qa = _latest_qa(verifier_engine, anomaly_id)
    assert qa["result"] == "REJECTED"
    assert qa["notes"] == "price changed before verification"


@pytest.mark.asyncio
async def test_flash_deal_escalated_when_verify_price_returns_none(verifier_engine: Engine) -> None:
    anomaly_id = _insert_anomaly(verifier_engine, tier="FLASH_DEAL", current_price=Decimal("100.00"))

    with Session(verifier_engine) as session:
        await verify_detected_anomalies(session, FakeAmadeusClient(None), anomaly_id=anomaly_id)
        session.commit()

    assert _anomaly_status(verifier_engine, anomaly_id) == "ESCALATED"
    qa = _latest_qa(verifier_engine, anomaly_id)
    assert qa["result"] == "ESCALATED"
    assert qa["notes"] == "verify_price unavailable"


@pytest.mark.asyncio
async def test_phantom_single_strike_amadeus_confirmed_stays_detected(verifier_engine: Engine) -> None:
    anomaly_id = _insert_anomaly(
        verifier_engine,
        tier="PHANTOM_FARE",
        current_price=Decimal("100.00"),
    )

    with Session(verifier_engine) as session:
        await verify_detected_anomalies(session, FakeAmadeusClient(_price_payload("100.50")), anomaly_id=anomaly_id)
        session.commit()

    assert _anomaly_status(verifier_engine, anomaly_id) == "DETECTED"
    qa = _latest_qa(verifier_engine, anomaly_id)
    assert qa["result"] == "CONFIRMED"
    assert qa["notes"] == "awaiting second strike or manual"


@pytest.mark.asyncio
async def test_phantom_two_strikes_and_manual_confirmed_becomes_verified(verifier_engine: Engine) -> None:
    first_bucket = datetime(2026, 5, 17, 10, tzinfo=UTC)
    _insert_anomaly(
        verifier_engine,
        tier="PHANTOM_FARE",
        current_price=Decimal("100.00"),
        bucket=first_bucket,
    )
    current_id = _insert_anomaly(
        verifier_engine,
        tier="PHANTOM_FARE",
        current_price=Decimal("100.00"),
        bucket=first_bucket + timedelta(hours=1),
    )
    _insert_manual_qa(verifier_engine, current_id, notes="human checked current fare")

    with Session(verifier_engine) as session:
        await verify_detected_anomalies(session, FakeAmadeusClient(_price_payload("100.00")), anomaly_id=current_id)
        session.commit()

    assert _anomaly_status(verifier_engine, current_id) == "VERIFIED"


@pytest.mark.asyncio
async def test_phantom_amadeus_and_duffel_confirmed_becomes_verified(verifier_engine: Engine) -> None:
    anomaly_id = _insert_anomaly(
        verifier_engine,
        tier="PHANTOM_FARE",
        current_price=Decimal("100.00"),
    )

    with Session(verifier_engine) as session:
        await verify_detected_anomalies(
            session,
            FakeAmadeusClient(_price_payload("100.00")),
            duffel_client=FakeDuffelClient(_price_payload("101.00")),
            anomaly_id=anomaly_id,
        )
        session.commit()

    assert _anomaly_status(verifier_engine, anomaly_id) == "VERIFIED"
    assert _qa_count(verifier_engine, anomaly_id, "CONFIRMED") == 2


def _price_payload(amount: str, currency: str = "USD") -> dict[str, Any]:
    return {"price": {"grandTotal": amount, "currency": currency}}


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
    current_price: Decimal,
    bucket: datetime | None = None,
) -> int:
    bucket = bucket or datetime(2026, 5, 17, 10, tzinfo=UTC)
    departure = date(2026, 7, 16)
    request_hash = f"verifier-{uuid.uuid4().hex}"
    with engine.begin() as connection:
        obs_id = int(
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
                        'ECONOMY', 60, :departure, NULL,
                        'USD', :current_price, 20.00,
                        'USD', :current_price, 1,
                        'AMADEUS', NULL, :request_hash, :bucket,
                        :observed_at, CAST(:raw_response AS jsonb)
                    )
                    RETURNING id
                    """
                ),
                {
                    "departure": departure,
                    "current_price": current_price,
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
                        :tier, :current_price, 400.00, 'USD',
                        300.00, 75.00, 0.950,
                        'test anomaly', 'SOW', 'DETECTED', :detected_at
                    )
                    RETURNING id
                    """
                ),
                {
                    "obs_id": obs_id,
                    "baseline_id": baseline_id,
                    "tier": tier,
                    "current_price": current_price,
                    "detected_at": bucket + timedelta(minutes=10),
                },
            ).scalar_one()
        )


def _insert_manual_qa(engine: Engine, anomaly_id: int, notes: str | None = None) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO qa_checks (
                    anomaly_id, verification_source, result, notes,
                    external_source_verified, checked_by
                )
                VALUES (:anomaly_id, 'MANUAL', 'CONFIRMED', :notes, false, 'test')
                """
            ),
            {"anomaly_id": anomaly_id, "notes": notes},
        )


def _anomaly_status(engine: Engine, anomaly_id: int) -> str:
    with engine.connect() as connection:
        return str(
            connection.execute(
                text("SELECT status FROM detected_anomalies WHERE id = :id"),
                {"id": anomaly_id},
            ).scalar_one()
        )


def _latest_qa(engine: Engine, anomaly_id: int) -> dict[str, Any]:
    with engine.connect() as connection:
        row = connection.execute(
            text(
                """
                SELECT verification_source, result, notes, verified_price, verified_currency
                FROM qa_checks
                WHERE anomaly_id = :id
                ORDER BY id DESC
                LIMIT 1
                """
            ),
            {"id": anomaly_id},
        ).one()
        return dict(row._mapping)


def _qa_count(engine: Engine, anomaly_id: int, result: str) -> int:
    with engine.connect() as connection:
        return int(
            connection.execute(
                text("SELECT count(*) FROM qa_checks WHERE anomaly_id = :id AND result = :result"),
                {"id": anomaly_id, "result": result},
            ).scalar_one()
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
