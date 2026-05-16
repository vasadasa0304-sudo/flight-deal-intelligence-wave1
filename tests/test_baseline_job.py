"""Tests for Wave1 rolling median baseline computation."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pandas as pd
import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from src.baselines.baseline_health import classify_health
from src.baselines.baseline_job import build_baselines, compute_stats

# Two watchlist rows seeded by _seed_reference():
#   watch_id=1  IST-DXB  TK  ECONOMY  14-day
#   watch_id=2  IST-DXB  TK  ECONOMY  60-day
_WATCH = {
    1: dict(route_id="IST-DXB", origin="IST", destination="DXB",
            airline_code="TK", cabin="ECONOMY", booking_window_days=14),
    2: dict(route_id="IST-DXB", origin="IST", destination="DXB",
            airline_code="TK", cabin="ECONOMY", booking_window_days=60),
}


# ---------------------------------------------------------------------------
# Helpers — pure DataFrame factory
# ---------------------------------------------------------------------------

def _obs_df(
    prices: list[float],
    *,
    watch_id: int = 1,
    booking_window_days: int = 60,
    native_currency: str = "USD",
) -> pd.DataFrame:
    """Build a minimal observations DataFrame for compute_stats."""
    return pd.DataFrame({
        "watch_id": watch_id,
        "route_id": "IST-DXB",
        "origin": "IST",
        "destination": "DXB",
        "airline_code": "TK",
        "cabin": "ECONOMY",
        "booking_window_days": booking_window_days,
        "native_currency": native_currency,
        "native_price": prices,
    })


# ---------------------------------------------------------------------------
# compute_stats — pure tests, no database
# ---------------------------------------------------------------------------

def test_compute_stats_flat_30_obs_all_stats_equal() -> None:
    stats = compute_stats(_obs_df([100.0] * 30))
    row = stats.iloc[0]
    assert len(stats) == 1
    assert row["median_price_native"] == pytest.approx(100.0)
    assert row["min_price_native"] == pytest.approx(100.0)
    assert row["max_price_native"] == pytest.approx(100.0)
    assert row["p25_price_native"] == pytest.approx(100.0)
    assert row["p75_price_native"] == pytest.approx(100.0)
    assert row["iqr_price_native"] == pytest.approx(0.0)
    assert int(row["observation_count"]) == 30


def test_compute_stats_mixed_prices_correct_percentiles() -> None:
    # 10 at 100, 10 at 110, 10 at 120 → median=110, p25=100, p75=120, iqr=20
    prices = [100.0] * 10 + [110.0] * 10 + [120.0] * 10
    stats = compute_stats(_obs_df(prices))
    row = stats.iloc[0]
    assert row["median_price_native"] == pytest.approx(110.0)
    assert row["p25_price_native"] == pytest.approx(100.0)
    assert row["p75_price_native"] == pytest.approx(120.0)
    assert row["iqr_price_native"] == pytest.approx(20.0)
    assert int(row["observation_count"]) == 30


def test_compute_stats_empty_df_returns_empty() -> None:
    assert compute_stats(pd.DataFrame()).empty


def test_compute_stats_14_and_60_day_windows_are_separate_rows() -> None:
    df = pd.concat([
        _obs_df([100.0] * 10, watch_id=1, booking_window_days=14),
        _obs_df([200.0] * 10, watch_id=2, booking_window_days=60),
    ], ignore_index=True)
    stats = compute_stats(df)
    assert len(stats) == 2
    windows = set(int(v) for v in stats["booking_window_days"])
    assert windows == {14, 60}


def test_compute_stats_two_currencies_produce_two_rows() -> None:
    df = pd.concat([
        _obs_df([150.0] * 15, watch_id=1, native_currency="USD"),
        _obs_df([130.0] * 15, watch_id=2, native_currency="EUR"),
    ], ignore_index=True)
    stats = compute_stats(df)
    assert len(stats) == 2
    assert set(stats["native_currency"]) == {"USD", "EUR"}


# ---------------------------------------------------------------------------
# classify_health — pure tests
# ---------------------------------------------------------------------------

def test_classify_health_good() -> None:
    assert classify_health(30, Decimal("0"), Decimal("100")) == "GOOD"


def test_classify_health_thin() -> None:
    assert classify_health(15, Decimal("0"), Decimal("100")) == "THIN"


def test_classify_health_missing_low_count() -> None:
    assert classify_health(5, Decimal("0"), Decimal("100")) == "MISSING"


def test_classify_health_missing_zero_count() -> None:
    assert classify_health(0, Decimal("0"), Decimal("0")) == "MISSING"


def test_classify_health_outlier_risk_overrides_good() -> None:
    # count=30 but iqr=60 > 0.5 * median=100 → OUTLIER_RISK, not GOOD
    assert classify_health(30, Decimal("60"), Decimal("100")) == "OUTLIER_RISK"


def test_classify_health_outlier_risk_overrides_thin() -> None:
    # count=15 in THIN range but high dispersion → OUTLIER_RISK
    assert classify_health(15, Decimal("60"), Decimal("100")) == "OUTLIER_RISK"


def test_classify_health_iqr_exactly_half_median_is_not_outlier() -> None:
    # Strict inequality: iqr=50 is NOT > 0.5*100=50
    assert classify_health(30, Decimal("50"), Decimal("100")) == "GOOD"


# ---------------------------------------------------------------------------
# DB fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def baseline_engine(pg_schema_engine: tuple[Engine, str]) -> Iterator[Engine]:
    engine, _ = pg_schema_engine
    _clear(engine)
    _seed_reference(engine)
    try:
        yield engine
    finally:
        _clear(engine)


# ---------------------------------------------------------------------------
# build_baselines — DB integration tests
# ---------------------------------------------------------------------------

def test_build_baselines_flat_price_inserts_correct_row(
    baseline_engine: Engine,
) -> None:
    baseline_date = date(2026, 6, 1)
    _insert_observations(baseline_engine, watch_id=1, prices=[100.0] * 30,
                         start_date=baseline_date - timedelta(days=30),
                         native_currency="EUR")

    with Session(baseline_engine) as session:
        count = build_baselines(session, baseline_date, watch_id=1)
        session.commit()

    assert count == 1
    row = _fetch_baseline(baseline_engine, watch_id=1, baseline_date=baseline_date)
    assert row.median_price_native == Decimal("100.00")
    assert row.min_price_native == Decimal("100.00")
    assert row.max_price_native == Decimal("100.00")
    assert row.iqr_price_native == Decimal("0.00")
    assert row.observation_count == 30
    assert row.baseline_health == "GOOD"
    assert row.window_start_date == baseline_date - timedelta(days=30)
    assert row.window_end_date == baseline_date - timedelta(days=1)


def test_build_baselines_five_obs_health_missing(
    baseline_engine: Engine,
) -> None:
    baseline_date = date(2026, 6, 1)
    _insert_observations(baseline_engine, watch_id=1, prices=[100.0] * 5,
                         start_date=baseline_date - timedelta(days=5),
                         native_currency="USD")

    with Session(baseline_engine) as session:
        build_baselines(session, baseline_date, watch_id=1)
        session.commit()

    row = _fetch_baseline(baseline_engine, watch_id=1, baseline_date=baseline_date)
    assert row.observation_count == 5
    assert row.baseline_health == "MISSING"


def test_build_baselines_mixed_prices_correct_percentiles(
    baseline_engine: Engine,
) -> None:
    baseline_date = date(2026, 6, 1)
    prices = [100.0] * 10 + [110.0] * 10 + [120.0] * 10
    _insert_observations(baseline_engine, watch_id=1, prices=prices,
                         start_date=baseline_date - timedelta(days=30),
                         native_currency="USD")

    with Session(baseline_engine) as session:
        build_baselines(session, baseline_date, watch_id=1)
        session.commit()

    row = _fetch_baseline(baseline_engine, watch_id=1, baseline_date=baseline_date)
    assert row.median_price_native == Decimal("110.00")
    assert row.p25_price_native == Decimal("100.00")
    assert row.p75_price_native == Decimal("120.00")
    assert row.iqr_price_native == Decimal("20.00")
    assert row.observation_count == 30


def test_build_baselines_idempotent(baseline_engine: Engine) -> None:
    baseline_date = date(2026, 6, 1)
    _insert_observations(baseline_engine, watch_id=1, prices=[100.0] * 30,
                         start_date=baseline_date - timedelta(days=30),
                         native_currency="USD")

    with Session(baseline_engine) as session:
        build_baselines(session, baseline_date, watch_id=1)
        session.commit()
    with Session(baseline_engine) as session:
        build_baselines(session, baseline_date, watch_id=1)
        session.commit()

    assert _count_baselines(baseline_engine) == 1


def test_build_baselines_14_and_60_day_windows_produce_separate_rows(
    baseline_engine: Engine,
) -> None:
    baseline_date = date(2026, 6, 1)
    _insert_observations(baseline_engine, watch_id=1, prices=[100.0] * 30,
                         start_date=baseline_date - timedelta(days=30),
                         native_currency="USD")
    _insert_observations(baseline_engine, watch_id=2, prices=[200.0] * 30,
                         start_date=baseline_date - timedelta(days=30),
                         native_currency="USD")

    with Session(baseline_engine) as session:
        count = build_baselines(session, baseline_date)
        session.commit()

    assert count == 2
    row14 = _fetch_baseline(baseline_engine, watch_id=1, baseline_date=baseline_date)
    row60 = _fetch_baseline(baseline_engine, watch_id=2, baseline_date=baseline_date)
    assert row14.booking_window_days == 14
    assert row60.booking_window_days == 60
    assert row14.median_price_native == Decimal("100.00")
    assert row60.median_price_native == Decimal("200.00")


def test_build_baselines_currency_segmented_produces_separate_rows(
    baseline_engine: Engine,
) -> None:
    baseline_date = date(2026, 6, 1)
    # watch_id=1 (14-day) observed in USD; watch_id=2 (60-day) observed in EUR
    _insert_observations(baseline_engine, watch_id=1, prices=[150.0] * 15,
                         start_date=baseline_date - timedelta(days=20),
                         native_currency="USD")
    _insert_observations(baseline_engine, watch_id=2, prices=[130.0] * 15,
                         start_date=baseline_date - timedelta(days=20),
                         native_currency="EUR")

    with Session(baseline_engine) as session:
        count = build_baselines(session, baseline_date)
        session.commit()

    assert count == 2
    row_usd = _fetch_baseline(baseline_engine, watch_id=1, baseline_date=baseline_date)
    row_eur = _fetch_baseline(baseline_engine, watch_id=2, baseline_date=baseline_date)
    assert row_usd.native_currency == "USD"
    assert row_eur.native_currency == "EUR"
    assert row_usd.median_price_native == Decimal("150.00")
    assert row_eur.median_price_native == Decimal("130.00")


def test_build_baselines_watch_id_filter_limits_output(
    baseline_engine: Engine,
) -> None:
    baseline_date = date(2026, 6, 1)
    _insert_observations(baseline_engine, watch_id=1, prices=[100.0] * 30,
                         start_date=baseline_date - timedelta(days=30),
                         native_currency="USD")
    _insert_observations(baseline_engine, watch_id=2, prices=[200.0] * 30,
                         start_date=baseline_date - timedelta(days=30),
                         native_currency="USD")

    with Session(baseline_engine) as session:
        count = build_baselines(session, baseline_date, watch_id=1)
        session.commit()

    assert count == 1
    assert _count_baselines(baseline_engine) == 1


def test_build_baselines_no_observations_returns_zero(
    baseline_engine: Engine,
) -> None:
    with Session(baseline_engine) as session:
        count = build_baselines(session, date(2026, 6, 1), watch_id=1)
        session.commit()

    assert count == 0
    assert _count_baselines(baseline_engine) == 0


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _seed_reference(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.exec_driver_sql(
            """
            INSERT INTO airports (airport_code, city, country, region, timezone, is_wave1_hub)
            VALUES
                ('IST', 'Istanbul', 'Turkey', 'Middle East + Turkey', 'Europe/Istanbul', true),
                ('DXB', 'Dubai', 'UAE', 'Middle East + Turkey', 'Asia/Dubai', true)
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
            VALUES ('IST-DXB', 'IST', 'DXB', 'INTERNATIONAL', 'STANDARD', 'STANDARD', 'test')
            """
        )
        connection.exec_driver_sql(
            """
            INSERT INTO watchlist (
                watch_id, route_id, airline_code, cabin, booking_window_days,
                currency, poll_frequency_minutes, route_priority, strategic_tag
            )
            VALUES
                (1, 'IST-DXB', 'TK', 'ECONOMY', 14, 'USD', 120, 'STANDARD', 'STANDARD'),
                (2, 'IST-DXB', 'TK', 'ECONOMY', 60, 'USD', 120, 'STANDARD', 'STANDARD')
            """
        )


def _insert_observations(
    engine: Engine,
    *,
    watch_id: int,
    prices: list[float],
    start_date: date,
    native_currency: str,
) -> None:
    """Insert one observation per price, each on a successive day from start_date."""
    watch = _WATCH[watch_id]
    with engine.begin() as connection:
        for i, price in enumerate(prices):
            obs_date = start_date + timedelta(days=i)
            obs_dt = datetime(obs_date.year, obs_date.month, obs_date.day, 10, 0, 0, tzinfo=UTC)
            connection.execute(
                text(
                    """
                    INSERT INTO price_observations (
                        watch_id, route_id, origin, destination,
                        airline_code, cabin, booking_window_days,
                        departure_date, native_currency, native_price,
                        display_currency, display_price,
                        source, request_hash, polling_bucket_hour, observed_at,
                        raw_response
                    ) VALUES (
                        :watch_id, :route_id, :origin, :destination,
                        :airline_code, :cabin, :booking_window_days,
                        :departure_date, :native_currency, :native_price,
                        :native_currency, :native_price,
                        'AMADEUS', :request_hash, :polling_bucket_hour, :observed_at,
                        '{}'::jsonb
                    )
                    """
                ),
                {
                    "watch_id": watch_id,
                    "route_id": watch["route_id"],
                    "origin": watch["origin"],
                    "destination": watch["destination"],
                    "airline_code": watch["airline_code"],
                    "cabin": watch["cabin"],
                    "booking_window_days": watch["booking_window_days"],
                    "departure_date": obs_date + timedelta(days=watch["booking_window_days"]),
                    "native_currency": native_currency,
                    "native_price": price,
                    "request_hash": f"test-{watch_id}-{i}",
                    "polling_bucket_hour": obs_dt,
                    "observed_at": obs_dt,
                },
            )


def _fetch_baseline(engine: Engine, *, watch_id: int, baseline_date: date) -> Any:
    with engine.connect() as connection:
        return connection.execute(
            text(
                "SELECT * FROM baselines WHERE watch_id = :wid AND baseline_date = :bd"
            ),
            {"wid": watch_id, "bd": baseline_date},
        ).one()


def _count_baselines(engine: Engine) -> int:
    with engine.connect() as connection:
        return int(
            connection.execute(text("SELECT count(*) FROM baselines")).scalar_one()
        )


def _clear(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.exec_driver_sql(
            """
            TRUNCATE TABLE baselines, price_observations, watchlist,
                           route_carriers, routes, airlines, airports
            RESTART IDENTITY CASCADE
            """
        )


# Silence the unused import warning — used in _fetch_baseline return type annotation
from typing import Any  # noqa: E402
