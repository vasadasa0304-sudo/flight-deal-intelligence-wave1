"""Tests for Wave1 backtest harness — replay and synthetic injection modes."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pandas as pd
import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from src.baselines.backtest import run_replay, run_synthetic

# ────────────────────────────────────────────────────── constants ─────────────

_ROUTE_ID = "IST-DXB"
_ORIGIN = "IST"
_DEST = "DXB"
_AIRLINE = "TK"
_CABIN = "ECONOMY"
_WINDOW = 60
_CURRENCY = "USD"
_WATCH_ID = 1

# Replay window
_START = date(2026, 4, 1)
_END = date(2026, 4, 30)

# Baseline price used in all fixtures; high enough for all tier thresholds:
#   DEAL:    45% off $400 = $220, saving $180 >= $80  ✓
#   FLASH:   65% off $400 = $140, saving $260 >= $150 ✓
#   PHANTOM: 80% off $400 = $80,  saving $320 >= $250 ✓
_BASELINE_PRICE = Decimal("400.00")
_DEAL_PRICE = Decimal("220.00")
_DEAL_DATE = date(2026, 4, 10)


# ────────────────────────────────────────────────────── fixtures ──────────────

@pytest.fixture()
def bt_engine(pg_schema_engine: tuple[Engine, str]) -> Iterator[Engine]:
    engine, _schema = pg_schema_engine
    _clear_all_rows(engine)
    _seed_reference_rows(engine)
    try:
        yield engine
    finally:
        _clear_all_rows(engine)


# ────────────────────────────────────────────────── Pass 1 (replay) ──────────

def test_replay_produces_non_empty_bt_baselines(bt_engine: Engine) -> None:
    _setup_replay_with_deal(bt_engine)

    with Session(bt_engine) as session:
        run_replay(session, start_date=_START, end_date=_END)

    with bt_engine.connect() as conn:
        n = conn.execute(text("SELECT COUNT(*) FROM bt_baselines")).scalar()
    assert n > 0, "bt_baselines must have rows after replay"


def test_replay_produces_non_empty_bt_detected_anomalies(bt_engine: Engine) -> None:
    _setup_replay_with_deal(bt_engine)

    with Session(bt_engine) as session:
        result = run_replay(session, start_date=_START, end_date=_END)

    assert result.n_anomalies >= 1, "at least one deal observation must be detected"
    with bt_engine.connect() as conn:
        n = conn.execute(text("SELECT COUNT(*) FROM bt_detected_anomalies")).scalar()
    assert n >= 1


def test_replay_writes_summary_and_per_route_csv(bt_engine: Engine) -> None:
    _setup_replay_with_deal(bt_engine)

    with Session(bt_engine) as session:
        result = run_replay(session, start_date=_START, end_date=_END)

    assert result.summary_path.exists(), "summary CSV must be created"
    assert result.per_route_path.exists(), "per-route CSV must be created"


def test_replay_summary_csv_reports_detected_deal(bt_engine: Engine) -> None:
    _setup_replay_with_deal(bt_engine)

    with Session(bt_engine) as session:
        result = run_replay(session, start_date=_START, end_date=_END)

    summary = pd.read_csv(result.summary_path)
    assert int(summary.iloc[0]["n_anomalies_deal"]) >= 1
    assert int(summary.iloc[0]["n_observations"]) == result.n_observations


def test_replay_does_not_touch_production_baselines(bt_engine: Engine) -> None:
    _setup_replay_with_deal(bt_engine)

    with bt_engine.connect() as conn:
        before = conn.execute(text("SELECT COUNT(*) FROM baselines")).scalar()

    with Session(bt_engine) as session:
        run_replay(session, start_date=_START, end_date=_END)

    with bt_engine.connect() as conn:
        after = conn.execute(text("SELECT COUNT(*) FROM baselines")).scalar()

    assert before == after, "replay must not write to production baselines table"


def test_replay_does_not_touch_production_detected_anomalies(bt_engine: Engine) -> None:
    _setup_replay_with_deal(bt_engine)

    with bt_engine.connect() as conn:
        before = conn.execute(text("SELECT COUNT(*) FROM detected_anomalies")).scalar()

    with Session(bt_engine) as session:
        run_replay(session, start_date=_START, end_date=_END)

    with bt_engine.connect() as conn:
        after = conn.execute(text("SELECT COUNT(*) FROM detected_anomalies")).scalar()

    assert before == after, "replay must not write to production detected_anomalies table"


def test_replay_does_not_touch_production_alerts(bt_engine: Engine) -> None:
    _setup_replay_with_deal(bt_engine)

    with bt_engine.connect() as conn:
        before = conn.execute(text("SELECT COUNT(*) FROM alerts")).scalar()

    with Session(bt_engine) as session:
        run_replay(session, start_date=_START, end_date=_END)

    with bt_engine.connect() as conn:
        after = conn.execute(text("SELECT COUNT(*) FROM alerts")).scalar()

    assert before == after, "replay must not write to production alerts table"


def test_replay_does_not_touch_production_price_observations(bt_engine: Engine) -> None:
    _setup_replay_with_deal(bt_engine)

    with bt_engine.connect() as conn:
        before = conn.execute(text("SELECT COUNT(*) FROM price_observations")).scalar()

    with Session(bt_engine) as session:
        run_replay(session, start_date=_START, end_date=_END)

    with bt_engine.connect() as conn:
        after = conn.execute(text("SELECT COUNT(*) FROM price_observations")).scalar()

    assert before == after, "replay only reads price_observations; must not write"


def test_replay_detected_anomaly_is_deal_tier(bt_engine: Engine) -> None:
    _setup_replay_with_deal(bt_engine)

    with Session(bt_engine) as session:
        run_replay(session, start_date=_START, end_date=_END)

    with bt_engine.connect() as conn:
        tiers = [
            r[0]
            for r in conn.execute(
                text("SELECT tier FROM bt_detected_anomalies WHERE is_synthetic = false")
            ).fetchall()
        ]
    assert tiers, "expected at least one detection"
    assert all(t == "DEAL" for t in tiers), f"unexpected tiers: {tiers}"


def test_replay_normal_observations_do_not_produce_anomalies(bt_engine: Engine) -> None:
    # All observations at baseline price — nothing should be detected.
    _insert_daily(bt_engine, date(2026, 3, 1), date(2026, 4, 30), _BASELINE_PRICE)

    with Session(bt_engine) as session:
        result = run_replay(session, start_date=_START, end_date=_END)

    assert result.n_anomalies == 0


def test_replay_empty_window_returns_empty_result(bt_engine: Engine) -> None:
    with Session(bt_engine) as session:
        result = run_replay(session, start_date=_START, end_date=_END)

    assert result.n_observations == 0
    assert result.n_anomalies == 0
    assert result.summary_path.exists()


# ────────────────────────────────────── Pass 2 (synthetic injection) ─────────

def test_synthetic_recall_is_1_for_all_tiers(bt_engine: Engine) -> None:
    # Daily observations across the full window give a GOOD baseline (>= 30 obs)
    # at end_date; injected savings clear all three SOW tier thresholds.
    _insert_daily(bt_engine, date(2026, 3, 1), date(2026, 4, 30), _BASELINE_PRICE)

    with Session(bt_engine) as session:
        result = run_synthetic(session, start_date=_START, end_date=_END)

    assert result.n_injected == 3, "expected 3 injected observations (one per tier)"
    for tier in ["DEAL", "FLASH_DEAL", "PHANTOM_FARE"]:
        recall = result.recall_by_tier.get(tier, -1.0)
        assert recall == 1.0, f"expected recall=1.0 for {tier}, got {recall}"


def test_synthetic_injected_obs_written_to_bt_synthetic_observations(bt_engine: Engine) -> None:
    _insert_daily(bt_engine, date(2026, 3, 1), date(2026, 4, 30), _BASELINE_PRICE)

    with Session(bt_engine) as session:
        run_synthetic(session, start_date=_START, end_date=_END)

    with bt_engine.connect() as conn:
        n = conn.execute(text("SELECT COUNT(*) FROM bt_synthetic_observations")).scalar()
    assert n == 3


def test_synthetic_detections_flagged_is_synthetic_true(bt_engine: Engine) -> None:
    _insert_daily(bt_engine, date(2026, 3, 1), date(2026, 4, 30), _BASELINE_PRICE)

    with Session(bt_engine) as session:
        run_synthetic(session, start_date=_START, end_date=_END)

    with bt_engine.connect() as conn:
        n = conn.execute(
            text("SELECT COUNT(*) FROM bt_detected_anomalies WHERE is_synthetic = true")
        ).scalar()
    assert n == 3


def test_synthetic_no_eligible_watch_ids_returns_empty_result(bt_engine: Engine) -> None:
    # Only ~12 daily obs → baseline never reaches GOOD (30) → no eligible watch_ids.
    _insert_daily(bt_engine, date(2026, 4, 1), date(2026, 4, 12), _BASELINE_PRICE)

    with Session(bt_engine) as session:
        result = run_synthetic(session, start_date=_START, end_date=_END)

    assert result.n_injected == 0
    assert result.recall_by_tier == {}


def test_synthetic_metrics_csv_exists(bt_engine: Engine) -> None:
    _insert_daily(bt_engine, date(2026, 3, 1), date(2026, 4, 30), _BASELINE_PRICE)

    with Session(bt_engine) as session:
        result = run_synthetic(session, start_date=_START, end_date=_END)

    assert result.metrics_path.exists()


# ──────────────────────────────────────────────── helper functions ────────────

def _setup_replay_with_deal(engine: Engine) -> None:
    """Daily baseline observations spanning the deal's lookback window + one deal.

    Baseline obs run Mar 22 → Apr 9 at $400 (19 rows); the Apr-10 deal at $220
    sees a 19-observation baseline window (THIN, non-MISSING) and is detected.
    Total fixture size: 20 observations on one route.
    """
    _insert_daily(engine, date(2026, 3, 22), date(2026, 4, 9), _BASELINE_PRICE)
    _insert_observation(
        engine,
        observed_at=datetime(_DEAL_DATE.year, _DEAL_DATE.month, _DEAL_DATE.day, 12, 0, 0, tzinfo=UTC),
        price=_DEAL_PRICE,
    )


def _insert_daily(engine: Engine, start: date, end: date, price: Decimal) -> int:
    """Insert one observation per calendar day in [start, end]. Returns the count."""
    count = 0
    current = start
    while current <= end:
        observed_at = datetime(current.year, current.month, current.day, 10, 0, 0, tzinfo=UTC)
        _insert_observation(engine, observed_at=observed_at, price=price)
        current += timedelta(days=1)
        count += 1
    return count


def _insert_observation(engine: Engine, *, observed_at: datetime, price: Decimal) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO price_observations (
                    watch_id, route_id, origin, destination, airline_code,
                    cabin, booking_window_days, departure_date,
                    native_currency, native_price, taxes_fees,
                    display_currency, display_price, fx_rate_used,
                    source, request_hash, polling_bucket_hour,
                    observed_at, raw_response
                )
                VALUES (
                    :watch_id, :route_id, :origin, :dest, :airline,
                    :cabin, :window, :departure_date,
                    :currency, :price, NULL,
                    :currency, :price, 1,
                    'AMADEUS', :request_hash, :bucket_hour,
                    :observed_at, CAST(:raw AS jsonb)
                )
                """
            ),
            {
                "watch_id": _WATCH_ID,
                "route_id": _ROUTE_ID,
                "origin": _ORIGIN,
                "dest": _DEST,
                "airline": _AIRLINE,
                "cabin": _CABIN,
                "window": _WINDOW,
                "departure_date": observed_at.date() + timedelta(days=_WINDOW),
                "currency": _CURRENCY,
                "price": price,
                "request_hash": str(uuid4()),
                "bucket_hour": observed_at.replace(minute=0, second=0, microsecond=0),
                "observed_at": observed_at,
                "raw": "{}",
            },
        )


def _seed_reference_rows(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.exec_driver_sql(
            """
            INSERT INTO airports (airport_code, city, country, region, timezone, is_wave1_hub)
            VALUES
                ('IST', 'Istanbul', 'Turkey', 'Middle East + Turkey', 'Europe/Istanbul', true),
                ('DXB', 'Dubai', 'UAE', 'Middle East + Turkey', 'Asia/Dubai', true)
            """
        )
        conn.exec_driver_sql(
            """
            INSERT INTO airlines (airline_code, airline_name, carrier_type, primary_hub, is_wave1_airline)
            VALUES ('TK', 'Turkish Airlines', 'FSC', 'IST', true)
            """
        )
        conn.exec_driver_sql(
            """
            INSERT INTO routes (
                route_id, origin, destination, route_type, route_priority,
                strategic_tag, source_document_note
            )
            VALUES ('IST-DXB', 'IST', 'DXB', 'INTERNATIONAL', 'STANDARD',
                    'STANDARD', 'test fixture')
            """
        )
        conn.exec_driver_sql(
            f"""
            INSERT INTO watchlist (
                watch_id, route_id, airline_code, cabin, booking_window_days,
                currency, poll_frequency_minutes, route_priority, strategic_tag
            )
            VALUES ({_WATCH_ID}, 'IST-DXB', 'TK', 'ECONOMY', {_WINDOW},
                    'USD', 120, 'STANDARD', 'STANDARD')
            """
        )


def _clear_all_rows(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.exec_driver_sql(
            """
            TRUNCATE TABLE
                bt_detected_anomalies, bt_baselines, bt_synthetic_observations,
                alerts, qa_checks, detected_anomalies, baselines,
                price_observations, scheduler_runs, api_request_logs,
                fx_rates, provider_budgets,
                watchlist, route_carriers, routes, airlines, airports
            RESTART IDENTITY CASCADE
            """
        )
