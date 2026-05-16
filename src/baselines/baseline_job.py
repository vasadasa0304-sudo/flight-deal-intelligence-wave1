"""30-day rolling median baseline computation for Wave1."""

from __future__ import annotations

import logging
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

from src.baselines.baseline_health import classify_health

logger = logging.getLogger(__name__)

_SQL_PATH = Path(__file__).parent / "baseline_queries.sql"

_TWO_PLACES = Decimal("0.01")


def compute_stats(observations_df: pd.DataFrame) -> pd.DataFrame:
    """Run DuckDB GROUP BY stats on a price_observations DataFrame.

    Expects columns: watch_id, route_id, origin, destination, airline_code,
    cabin, booking_window_days, native_currency, native_price (numeric).
    Returns one row per unique grouping key.
    """
    if observations_df.empty:
        return pd.DataFrame()

    sql = _SQL_PATH.read_text(encoding="utf-8")
    conn = duckdb.connect()
    try:
        conn.register("obs", observations_df)
        result = conn.execute(sql).df()
    finally:
        conn.close()
    return result


def build_baselines(
    session: Session,
    baseline_date: date,
    watch_id: int | None = None,
) -> int:
    """Load the 30-day observation window, compute stats, and upsert baseline rows.

    Window: [baseline_date - 30, baseline_date - 1] inclusive on observed_at date.
    Returns the number of rows upserted.
    """
    window_start = baseline_date - timedelta(days=30)
    window_end = baseline_date - timedelta(days=1)

    obs_df = _load_observations(session, window_start, window_end, watch_id)
    if obs_df.empty:
        logger.info(
            "No observations in window %s–%s watch_id=%s.",
            window_start,
            window_end,
            watch_id,
        )
        return 0

    stats_df = compute_stats(obs_df)
    if stats_df.empty:
        return 0

    upserted = 0
    for _, row in stats_df.iterrows():
        health = classify_health(
            int(row["observation_count"]),
            Decimal(str(row["iqr_price_native"])).quantize(_TWO_PLACES),
            Decimal(str(row["median_price_native"])).quantize(_TWO_PLACES),
        )
        _upsert_baseline(
            session,
            row=row,
            baseline_date=baseline_date,
            window_start=window_start,
            window_end=window_end,
            health=health,
        )
        upserted += 1

    logger.info(
        "Baselines upserted: %d for baseline_date=%s watch_id=%s.",
        upserted,
        baseline_date,
        watch_id,
    )
    return upserted


def _load_observations(
    session: Session,
    window_start: date,
    window_end: date,
    watch_id: int | None,
) -> pd.DataFrame:
    query = """
        SELECT
            watch_id, route_id, origin, destination,
            airline_code, cabin, booking_window_days,
            native_currency, native_price::double precision AS native_price
        FROM price_observations
        WHERE observed_at::date >= :window_start
          AND observed_at::date <= :window_end
    """
    params: dict[str, Any] = {"window_start": window_start, "window_end": window_end}
    if watch_id is not None:
        query += " AND watch_id = :watch_id"
        params["watch_id"] = watch_id

    result = session.execute(text(query), params)
    rows = result.fetchall()
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows, columns=list(result.keys()))


def _upsert_baseline(
    session: Session,
    *,
    row: Any,
    baseline_date: date,
    window_start: date,
    window_end: date,
    health: str,
) -> None:
    def _dec(value: Any) -> Decimal:
        return Decimal(str(value)).quantize(_TWO_PLACES)

    session.execute(
        text(
            """
            INSERT INTO baselines (
                watch_id, route_id, origin, destination, airline_code, cabin,
                booking_window_days, native_currency,
                baseline_date, window_start_date, window_end_date,
                median_price_native, min_price_native, max_price_native,
                p25_price_native, p75_price_native, iqr_price_native,
                observation_count, baseline_health
            )
            VALUES (
                :watch_id, :route_id, :origin, :destination, :airline_code, :cabin,
                :booking_window_days, :native_currency,
                :baseline_date, :window_start_date, :window_end_date,
                :median_price_native, :min_price_native, :max_price_native,
                :p25_price_native, :p75_price_native, :iqr_price_native,
                :observation_count, :baseline_health
            )
            ON CONFLICT ON CONSTRAINT uq_baselines_watch_date DO UPDATE SET
                route_id            = EXCLUDED.route_id,
                origin              = EXCLUDED.origin,
                destination         = EXCLUDED.destination,
                airline_code        = EXCLUDED.airline_code,
                cabin               = EXCLUDED.cabin,
                booking_window_days = EXCLUDED.booking_window_days,
                native_currency     = EXCLUDED.native_currency,
                window_start_date   = EXCLUDED.window_start_date,
                window_end_date     = EXCLUDED.window_end_date,
                median_price_native = EXCLUDED.median_price_native,
                min_price_native    = EXCLUDED.min_price_native,
                max_price_native    = EXCLUDED.max_price_native,
                p25_price_native    = EXCLUDED.p25_price_native,
                p75_price_native    = EXCLUDED.p75_price_native,
                iqr_price_native    = EXCLUDED.iqr_price_native,
                observation_count   = EXCLUDED.observation_count,
                baseline_health     = EXCLUDED.baseline_health
            """
        ),
        {
            "watch_id": int(row["watch_id"]),
            "route_id": str(row["route_id"]),
            "origin": str(row["origin"]),
            "destination": str(row["destination"]),
            "airline_code": str(row["airline_code"]),
            "cabin": str(row["cabin"]),
            "booking_window_days": int(row["booking_window_days"]),
            "native_currency": str(row["native_currency"]),
            "baseline_date": baseline_date,
            "window_start_date": window_start,
            "window_end_date": window_end,
            "median_price_native": _dec(row["median_price_native"]),
            "min_price_native": _dec(row["min_price_native"]),
            "max_price_native": _dec(row["max_price_native"]),
            "p25_price_native": _dec(row["p25_price_native"]),
            "p75_price_native": _dec(row["p75_price_native"]),
            "iqr_price_native": _dec(row["iqr_price_native"]),
            "observation_count": int(row["observation_count"]),
            "baseline_health": health,
        },
    )
