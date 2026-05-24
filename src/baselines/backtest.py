"""Wave1 backtest harness — replay and synthetic injection modes.

Pass 1 (replay):  replays real price_observations through baseline + detector
                  into bt_ mirror tables; writes summary and per-route CSVs.
Pass 2 (synthetic): injects synthetic deal observations at known savings,
                    measures detector precision/recall; writes metrics CSV.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

from src.baselines.baseline_health import classify_health
from src.baselines.baseline_job import compute_stats
from src.detection.detector import DetectionCandidate, classify_observation_pair
from src.detection.thresholds import THRESHOLD_SET_SOW

logger = logging.getLogger(__name__)

_MONEY = Decimal("0.01")
_EXPORTS_DIR = Path("data/exports/backtests")
_CONFIRMATION_TOLERANCE = Decimal("0.05")

# Synthetic injection savings per tier (fraction of baseline median).
_SYNTHETIC_SAVINGS: dict[str, Decimal] = {
    "DEAL": Decimal("0.45"),
    "FLASH_DEAL": Decimal("0.65"),
    "PHANTOM_FARE": Decimal("0.80"),
}
_SYNTHETIC_TIER_ORDER = ["DEAL", "FLASH_DEAL", "PHANTOM_FARE"]


# ─────────────────────────────────────── result dataclasses ──────────────────

@dataclass(frozen=True)
class ReplayResult:
    """Pass 1 replay backtest outcome."""

    window: str
    n_observations: int
    n_baselines_built: int
    n_anomalies: int
    summary_path: Path
    per_route_path: Path


@dataclass(frozen=True)
class SyntheticResult:
    """Pass 2 synthetic injection outcome."""

    window: str
    n_injected: int
    recall_by_tier: dict[str, float]
    precision_by_tier: dict[str, float]
    metrics_path: Path


# ─────────────────────────────────────── public API ──────────────────────────

def run_replay(
    session: Session,
    start_date: date,
    end_date: date,
    threshold_set: str = THRESHOLD_SET_SOW,
) -> ReplayResult:
    """Replay all price_observations in [start_date, end_date] into bt_ tables.

    For each calendar day in the window, builds a 30-day rolling baseline into
    bt_baselines then classifies each observation into bt_detected_anomalies.
    Writes two CSVs under data/exports/backtests/.
    Does NOT write to any production table.
    """
    _truncate_bt_tables(session)
    session.commit()

    observations = _load_window_observations(session, start_date, end_date)
    if not observations:
        logger.info("No observations in window %s–%s.", start_date, end_date)
        return _empty_replay_result(start_date, end_date)

    obs_by_date: dict[date, list[dict[str, Any]]] = {}
    for obs in observations:
        d = _as_utc(obs["observed_at"]).date()
        obs_by_date.setdefault(d, []).append(obs)

    n_baselines = 0
    n_anomalies = 0
    for day in sorted(obs_by_date):
        for watch_id in {o["watch_id"] for o in obs_by_date[day]}:
            n_baselines += _build_bt_baseline(session, baseline_date=day, watch_id=watch_id)
        session.commit()

        for obs in obs_by_date[day]:
            baseline = _bt_latest_baseline(session, obs)
            if baseline is None:
                continue
            candidate = classify_observation_pair(
                session,
                observation=obs,
                baseline=baseline,
                threshold_set=threshold_set,
            )
            if candidate is not None:
                _bt_insert_detection(session, candidate, is_synthetic=False)
                n_anomalies += 1
        session.commit()

    window_str = f"{start_date}_{end_date}"
    _EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    summary_df, per_route_df = _build_replay_dataframes(
        session, observations, start_date, end_date, threshold_set
    )
    summary_path = _EXPORTS_DIR / f"replay_{window_str}_summary.csv"
    per_route_path = _EXPORTS_DIR / f"replay_{window_str}_per_route.csv"
    summary_df.to_csv(summary_path, index=False)
    per_route_df.to_csv(per_route_path, index=False)

    logger.info(
        "Replay %s–%s: %d obs, %d baselines, %d anomalies → %s / %s",
        start_date, end_date, len(observations), n_baselines, n_anomalies,
        summary_path.name, per_route_path.name,
    )
    return ReplayResult(
        window=window_str,
        n_observations=len(observations),
        n_baselines_built=n_baselines,
        n_anomalies=n_anomalies,
        summary_path=summary_path,
        per_route_path=per_route_path,
    )


def run_synthetic(
    session: Session,
    start_date: date,
    end_date: date,
    threshold_set: str = THRESHOLD_SET_SOW,
) -> SyntheticResult:
    """Inject synthetic deal fares and measure detector precision/recall.

    Requires watch_ids with health=GOOD baselines (observation_count >= 30).
    Injects three synthetic observations per eligible watch_id — one per tier
    at the canonical savings fractions (45 / 65 / 80 %).
    """
    _truncate_bt_tables(session)
    session.commit()

    real_obs = _load_window_observations(session, start_date, end_date)

    # Build bt_baselines (same as replay)
    obs_by_date: dict[date, list[dict[str, Any]]] = {}
    for obs in real_obs:
        d = _as_utc(obs["observed_at"]).date()
        obs_by_date.setdefault(d, []).append(obs)
    for day in sorted(obs_by_date):
        for watch_id in {o["watch_id"] for o in obs_by_date[day]}:
            _build_bt_baseline(session, baseline_date=day, watch_id=watch_id)
    session.commit()

    eligible = _eligible_watch_ids(session, start_date, end_date)
    if not eligible:
        logger.warning("No GOOD-health baselines found; no synthetic injection possible.")
        return _empty_synthetic_result(start_date, end_date)

    synthetic_obs = _inject_synthetic_observations(session, eligible, end_date)
    session.commit()

    # Run detector on real observations
    for obs in real_obs:
        baseline = _bt_latest_baseline(session, obs)
        if baseline is None:
            continue
        candidate = classify_observation_pair(
            session, observation=obs, baseline=baseline, threshold_set=threshold_set
        )
        if candidate is not None:
            _bt_insert_detection(session, candidate, is_synthetic=False)
    session.commit()

    # Run detector on synthetic observations
    for obs in synthetic_obs:
        baseline = _bt_latest_baseline(session, obs)
        if baseline is None:
            continue
        candidate = classify_observation_pair(
            session, observation=obs, baseline=baseline, threshold_set=threshold_set
        )
        if candidate is not None:
            _bt_insert_detection(session, candidate, is_synthetic=True)
    session.commit()

    metrics_df = _build_synthetic_metrics(session, synthetic_obs, real_obs)
    window_str = f"{start_date}_{end_date}"
    _EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    metrics_path = _EXPORTS_DIR / f"synthetic_{window_str}_metrics.csv"
    metrics_df.to_csv(metrics_path, index=False)

    recall_by_tier: dict[str, float] = {}
    precision_by_tier: dict[str, float] = {}
    for _, row in metrics_df.iterrows():
        tier = str(row["tier"])
        recall_by_tier[tier] = float(row["recall"])
        precision_by_tier[tier] = float(row["precision"])

    logger.info(
        "Synthetic %s–%s: %d injected, recall=%s → %s",
        start_date, end_date, len(synthetic_obs),
        {t: f"{v:.2f}" for t, v in recall_by_tier.items()},
        metrics_path.name,
    )
    return SyntheticResult(
        window=window_str,
        n_injected=len(synthetic_obs),
        recall_by_tier=recall_by_tier,
        precision_by_tier=precision_by_tier,
        metrics_path=metrics_path,
    )


# ─────────────────────────────────────── bt_baselines helpers ────────────────

def _build_bt_baseline(
    session: Session,
    baseline_date: date,
    watch_id: int,
) -> int:
    """Build one 30-day rolling baseline into bt_baselines. Returns rows upserted."""
    window_start = baseline_date - timedelta(days=30)
    window_end = baseline_date - timedelta(days=1)
    obs_df = _load_baseline_window_obs(session, window_start, window_end, watch_id)
    if obs_df.empty:
        return 0
    stats_df = compute_stats(obs_df)
    if stats_df.empty:
        return 0

    upserted = 0
    for _, row in stats_df.iterrows():
        health = classify_health(
            int(row["observation_count"]),
            Decimal(str(row["iqr_price_native"])).quantize(_MONEY),
            Decimal(str(row["median_price_native"])).quantize(_MONEY),
        )
        _bt_upsert_baseline(
            session,
            row=row,
            baseline_date=baseline_date,
            window_start=window_start,
            window_end=window_end,
            health=health,
        )
        upserted += 1
    return upserted


def _bt_upsert_baseline(
    session: Session,
    *,
    row: Any,
    baseline_date: date,
    window_start: date,
    window_end: date,
    health: str,
) -> None:
    def _d(v: Any) -> Decimal:
        return Decimal(str(v)).quantize(_MONEY, rounding=ROUND_HALF_UP)

    session.execute(
        text(
            """
            INSERT INTO bt_baselines (
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
                :baseline_date, :window_start, :window_end,
                :median, :min, :max, :p25, :p75, :iqr,
                :obs_count, :health
            )
            ON CONFLICT ON CONSTRAINT bt_uq_baselines_watch_date DO UPDATE SET
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
            "window_start": window_start,
            "window_end": window_end,
            "median": _d(row["median_price_native"]),
            "min": _d(row["min_price_native"]),
            "max": _d(row["max_price_native"]),
            "p25": _d(row["p25_price_native"]),
            "p75": _d(row["p75_price_native"]),
            "iqr": _d(row["iqr_price_native"]),
            "obs_count": int(row["observation_count"]),
            "health": health,
        },
    )


def _bt_latest_baseline(
    session: Session,
    observation: dict[str, Any],
) -> dict[str, Any] | None:
    """Return the most recent bt_baselines row applicable to this observation."""
    result = session.execute(
        text(
            """
            SELECT
                id, watch_id, route_id, origin, destination, airline_code,
                cabin, booking_window_days, native_currency, baseline_date,
                median_price_native, observation_count, baseline_health, created_at
            FROM bt_baselines
            WHERE watch_id            = :watch_id
              AND route_id            = :route_id
              AND airline_code        = :airline_code
              AND cabin               = :cabin
              AND booking_window_days = :booking_window_days
              AND native_currency     = :native_currency
              AND baseline_date       <= :observed_date
            ORDER BY baseline_date DESC, created_at DESC, id DESC
            LIMIT 1
            """
        ),
        {
            "watch_id": observation["watch_id"],
            "route_id": observation["route_id"],
            "airline_code": observation["airline_code"],
            "cabin": observation["cabin"],
            "booking_window_days": observation["booking_window_days"],
            "native_currency": observation["native_currency"],
            "observed_date": _as_utc(observation["observed_at"]).date(),
        },
    ).first()
    return dict(result._mapping) if result is not None else None


# ─────────────────────────────────────── bt_detected_anomalies helpers ───────

def _bt_insert_detection(
    session: Session,
    candidate: DetectionCandidate,
    is_synthetic: bool,
) -> bool:
    result = session.execute(
        text(
            """
            INSERT INTO bt_detected_anomalies (
                price_observation_id, baseline_id, watch_id, tier,
                current_price, baseline_price, currency, absolute_saving,
                percent_saving, confidence_score, detection_reason,
                threshold_set, is_synthetic
            )
            VALUES (
                :price_observation_id, :baseline_id, :watch_id, :tier,
                :current_price, :baseline_price, :currency, :absolute_saving,
                :percent_saving, :confidence_score, :detection_reason,
                :threshold_set, :is_synthetic
            )
            RETURNING id
            """
        ),
        {
            "price_observation_id": candidate.price_observation_id,
            "baseline_id": candidate.baseline_id,
            "watch_id": candidate.watch_id,
            "tier": candidate.tier,
            "current_price": candidate.current_price,
            "baseline_price": candidate.baseline_price,
            "currency": candidate.currency,
            "absolute_saving": candidate.absolute_saving,
            "percent_saving": candidate.percent_saving,
            "confidence_score": candidate.confidence_score,
            "detection_reason": candidate.detection_reason,
            "threshold_set": candidate.threshold_set,
            "is_synthetic": is_synthetic,
        },
    )
    return result.scalar_one_or_none() is not None


# ─────────────────────────────────────── data loading ────────────────────────

def _load_window_observations(
    session: Session,
    start_date: date,
    end_date: date,
) -> list[dict[str, Any]]:
    result = session.execute(
        text(
            """
            SELECT
                id, watch_id, route_id, origin, destination, airline_code,
                cabin, booking_window_days, native_currency, native_price,
                observed_at
            FROM price_observations
            WHERE observed_at::date >= :start_date
              AND observed_at::date <= :end_date
            ORDER BY observed_at ASC, id ASC
            """
        ),
        {"start_date": start_date, "end_date": end_date},
    )
    return [dict(r._mapping) for r in result]


def _load_baseline_window_obs(
    session: Session,
    window_start: date,
    window_end: date,
    watch_id: int,
) -> pd.DataFrame:
    result = session.execute(
        text(
            """
            SELECT
                watch_id, route_id, origin, destination,
                airline_code, cabin, booking_window_days,
                native_currency,
                native_price::double precision AS native_price
            FROM price_observations
            WHERE watch_id = :watch_id
              AND observed_at::date >= :window_start
              AND observed_at::date <= :window_end
            """
        ),
        {"watch_id": watch_id, "window_start": window_start, "window_end": window_end},
    )
    rows = result.fetchall()
    return pd.DataFrame(rows, columns=list(result.keys())) if rows else pd.DataFrame()


# ─────────────────────────────────────── synthetic helpers ───────────────────

def _eligible_watch_ids(
    session: Session,
    start_date: date,
    end_date: date,
) -> list[dict[str, Any]]:
    """Return one bt_baselines row per watch_id that has health=GOOD in the window."""
    result = session.execute(
        text(
            """
            SELECT DISTINCT ON (b.watch_id)
                b.watch_id, b.route_id, b.origin, b.destination,
                b.airline_code, b.cabin, b.booking_window_days,
                b.native_currency, b.median_price_native
            FROM bt_baselines b
            WHERE b.baseline_health = 'GOOD'
              AND b.baseline_date BETWEEN :start AND :end
            ORDER BY b.watch_id, b.baseline_date DESC
            """
        ),
        {"start": start_date, "end": end_date},
    )
    return [dict(r._mapping) for r in result]


def _inject_synthetic_observations(
    session: Session,
    eligible: list[dict[str, Any]],
    inject_date: date,
) -> list[dict[str, Any]]:
    """Insert three synthetic fares per eligible watch_id into bt_synthetic_observations."""
    inject_at = datetime(
        inject_date.year, inject_date.month, inject_date.day,
        12, 0, 0, tzinfo=UTC,
    )
    inserted: list[dict[str, Any]] = []

    for watch in eligible:
        median = Decimal(str(watch["median_price_native"])).quantize(
            _MONEY, rounding=ROUND_HALF_UP
        )
        if median <= 0:
            continue

        for tier in _SYNTHETIC_TIER_ORDER:
            saving_frac = _SYNTHETIC_SAVINGS[tier]
            injected_price = max(
                Decimal("0.00"),
                (median * (Decimal("1") - saving_frac)).quantize(_MONEY, rounding=ROUND_HALF_UP),
            )

            row_id = session.execute(
                text(
                    """
                    INSERT INTO bt_synthetic_observations (
                        watch_id, route_id, origin, destination, airline_code,
                        cabin, booking_window_days, departure_date,
                        native_currency, native_price,
                        display_currency, display_price,
                        observed_at, injected_tier, injected_saving_pct
                    )
                    VALUES (
                        :watch_id, :route_id, :origin, :destination, :airline_code,
                        :cabin, :booking_window_days, :departure_date,
                        :currency, :native_price,
                        :currency, :native_price,
                        :observed_at, :tier, :saving_pct
                    )
                    RETURNING id
                    """
                ),
                {
                    "watch_id": watch["watch_id"],
                    "route_id": watch["route_id"],
                    "origin": watch["origin"],
                    "destination": watch["destination"],
                    "airline_code": watch["airline_code"],
                    "cabin": watch["cabin"],
                    "booking_window_days": watch["booking_window_days"],
                    "departure_date": inject_date + timedelta(days=int(watch["booking_window_days"])),
                    "currency": watch["native_currency"],
                    "native_price": injected_price,
                    "observed_at": inject_at,
                    "tier": tier,
                    "saving_pct": float(saving_frac * 100),
                },
            ).scalar_one()

            inserted.append({
                "id": row_id,
                "watch_id": watch["watch_id"],
                "route_id": watch["route_id"],
                "origin": watch["origin"],
                "destination": watch["destination"],
                "airline_code": watch["airline_code"],
                "cabin": watch["cabin"],
                "booking_window_days": watch["booking_window_days"],
                "native_currency": watch["native_currency"],
                "native_price": injected_price,
                "observed_at": inject_at,
                "injected_tier": tier,
            })

    return inserted


# ─────────────────────────────────────── stats builders ──────────────────────

def _build_replay_dataframes(
    session: Session,
    observations: list[dict[str, Any]],
    start_date: date,
    end_date: date,
    threshold_set: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    obs_df = pd.DataFrame(observations)

    anomalies_raw = session.execute(
        text(
            "SELECT id, price_observation_id, watch_id, tier, current_price "
            "FROM bt_detected_anomalies WHERE is_synthetic = false"
        )
    )
    anomalies_df = pd.DataFrame(
        [dict(r._mapping) for r in anomalies_raw],
    )
    if anomalies_df.empty:
        anomalies_df = pd.DataFrame(
            columns=["id", "price_observation_id", "watch_id", "tier", "current_price"]
        )

    baselines_raw = session.execute(
        text(
            "SELECT watch_id, route_id, airline_code, cabin, "
            "booking_window_days, baseline_health FROM bt_baselines"
        )
    )
    baselines_df = pd.DataFrame([dict(r._mapping) for r in baselines_raw])
    if baselines_df.empty:
        baselines_df = pd.DataFrame(
            columns=["watch_id", "route_id", "airline_code", "cabin",
                     "booking_window_days", "baseline_health"]
        )

    per_route_key = ["route_id", "airline_code", "cabin", "booking_window_days"]

    # Simulation: shift to find next price for each watch_id within the window
    n_confirmed_total = 0
    n_rejected_total = 0
    sim_merged = pd.DataFrame()

    if not anomalies_df.empty and not obs_df.empty:
        obs_sim = obs_df.sort_values(["watch_id", "observed_at"]).copy()
        obs_sim["next_native_price"] = obs_sim.groupby("watch_id")["native_price"].shift(-1)

        sim_merged = anomalies_df.merge(
            obs_sim[["id", "route_id", "airline_code", "cabin",
                     "booking_window_days", "next_native_price"]],
            left_on="price_observation_id",
            right_on="id",
            how="left",
            suffixes=("", "_obs"),
        )
        sim_merged["current_price"] = pd.to_numeric(sim_merged["current_price"])
        sim_merged["next_native_price"] = pd.to_numeric(sim_merged["next_native_price"])
        price_diff_pct = (
            (sim_merged["next_native_price"] - sim_merged["current_price"]).abs()
            / sim_merged["current_price"].replace(0, float("nan"))
        )
        sim_merged["is_confirmed"] = (
            sim_merged["next_native_price"].isna() | (price_diff_pct <= 0.05)
        )
        n_confirmed_total = int(sim_merged["is_confirmed"].sum())
        n_rejected_total = int((~sim_merged["is_confirmed"]).sum())

    # Per-route observation counts
    n_obs_per_route = (
        obs_df.groupby(per_route_key, as_index=False).agg(n_observations=("id", "count"))
        if not obs_df.empty
        else pd.DataFrame(columns=per_route_key + ["n_observations"])
    )

    # Per-route anomaly counts + simulation breakdown
    per_route_anomalies = pd.DataFrame()
    if not sim_merged.empty:
        tiers_pivot = (
            sim_merged.groupby(per_route_key + ["tier"])
            .size()
            .unstack("tier", fill_value=0)
            .reset_index()
        )
        for col in ["DEAL", "FLASH_DEAL", "PHANTOM_FARE"]:
            if col not in tiers_pivot.columns:
                tiers_pivot[col] = 0
        confirmed_pivot = (
            sim_merged.groupby(per_route_key)
            .agg(
                n_simulated_confirmed=("is_confirmed", "sum"),
                n_simulated_rejected=("is_confirmed", lambda x: (~x).sum()),
            )
            .reset_index()
        )
        per_route_anomalies = tiers_pivot.merge(confirmed_pivot, on=per_route_key, how="outer")
        per_route_anomalies = per_route_anomalies.rename(
            columns={"DEAL": "n_deal", "FLASH_DEAL": "n_flash_deal", "PHANTOM_FARE": "n_phantom_fare"}
        )

    # Baseline health distribution per route
    health_pivot = pd.DataFrame()
    if not baselines_df.empty:
        health_pivot = (
            baselines_df.groupby(per_route_key + ["baseline_health"])
            .size()
            .unstack("baseline_health", fill_value=0)
            .reset_index()
        )
        for col in ["GOOD", "THIN", "MISSING", "OUTLIER_RISK"]:
            if col not in health_pivot.columns:
                health_pivot[col] = 0
        health_pivot = health_pivot.rename(columns={
            "GOOD": "health_good", "THIN": "health_thin",
            "MISSING": "health_missing", "OUTLIER_RISK": "health_outlier_risk",
        })

    per_route = n_obs_per_route
    if not per_route_anomalies.empty:
        per_route = per_route.merge(per_route_anomalies, on=per_route_key, how="left")
    if not health_pivot.empty:
        per_route = per_route.merge(health_pivot, on=per_route_key, how="left")

    int_cols = [
        "n_deal", "n_flash_deal", "n_phantom_fare",
        "n_simulated_confirmed", "n_simulated_rejected",
        "health_good", "health_thin", "health_missing", "health_outlier_risk",
    ]
    for col in int_cols:
        if col not in per_route.columns:
            per_route[col] = 0
        per_route[col] = per_route[col].fillna(0).astype(int)
    per_route["n_anomalies_total"] = (
        per_route["n_deal"] + per_route["n_flash_deal"] + per_route["n_phantom_fare"]
    )

    n_deal = int((anomalies_df["tier"] == "DEAL").sum()) if not anomalies_df.empty else 0
    n_flash = int((anomalies_df["tier"] == "FLASH_DEAL").sum()) if not anomalies_df.empty else 0
    n_phantom = int((anomalies_df["tier"] == "PHANTOM_FARE").sum()) if not anomalies_df.empty else 0
    bh = baselines_df["baseline_health"].value_counts().to_dict() if not baselines_df.empty else {}

    summary = pd.DataFrame([{
        "start_date": str(start_date),
        "end_date": str(end_date),
        "threshold_set": threshold_set,
        "n_observations": len(observations),
        "n_baselines_built": len(baselines_df),
        "n_anomalies_deal": n_deal,
        "n_anomalies_flash_deal": n_flash,
        "n_anomalies_phantom_fare": n_phantom,
        "n_anomalies_total": n_deal + n_flash + n_phantom,
        "n_simulated_confirmed": n_confirmed_total,
        "n_simulated_rejected": n_rejected_total,
        "health_good": bh.get("GOOD", 0),
        "health_thin": bh.get("THIN", 0),
        "health_missing": bh.get("MISSING", 0),
        "health_outlier_risk": bh.get("OUTLIER_RISK", 0),
    }])

    return summary, per_route


def _build_synthetic_metrics(
    session: Session,
    synthetic_obs: list[dict[str, Any]],
    real_obs: list[dict[str, Any]],
) -> pd.DataFrame:
    """Compute per-tier precision/recall and real-observation rejection rate."""
    syn_det_ids = {
        r[0]
        for r in session.execute(
            text("SELECT price_observation_id FROM bt_detected_anomalies WHERE is_synthetic = true")
        ).fetchall()
    }

    tier_stats: dict[str, dict[str, int]] = {}
    for obs in synthetic_obs:
        tier = obs["injected_tier"]
        tier_stats.setdefault(tier, {"injected": 0, "detected": 0})
        tier_stats[tier]["injected"] += 1
        if obs["id"] in syn_det_ids:
            tier_stats[tier]["detected"] += 1

    # Real-observation false positives (simulated rejections)
    total_fp = 0
    total_real_det = 0
    if real_obs:
        real_obs_df = pd.DataFrame(real_obs).sort_values(["watch_id", "observed_at"])
        real_obs_df["next_price"] = real_obs_df.groupby("watch_id")["native_price"].shift(-1)
        real_obs_map = real_obs_df.set_index("id")[["next_price"]].to_dict("index")

        real_det_rows = session.execute(
            text("SELECT price_observation_id, current_price FROM bt_detected_anomalies WHERE is_synthetic = false")
        ).fetchall()
        total_real_det = len(real_det_rows)

        for row in real_det_rows:
            obs_id = row[0]
            current = Decimal(str(row[1]))
            next_raw = real_obs_map.get(obs_id, {}).get("next_price")
            if next_raw is None or pd.isna(next_raw):
                continue
            if current > 0 and abs(Decimal(str(next_raw)) - current) / current > _CONFIRMATION_TOLERANCE:
                total_fp += 1

    rejection_rate = round(total_fp / total_real_det, 4) if total_real_det > 0 else 0.0

    records = []
    for tier in _SYNTHETIC_TIER_ORDER:
        stats = tier_stats.get(tier, {"injected": 0, "detected": 0})
        tp = stats["detected"]
        injected = stats["injected"]
        precision = round(tp / (tp + total_fp), 4) if (tp + total_fp) > 0 else 0.0
        recall = round(tp / injected, 4) if injected > 0 else 0.0
        records.append({
            "tier": tier,
            "injected_count": injected,
            "true_positives": tp,
            "false_positive_count": total_fp,
            "precision": precision,
            "recall": recall,
            "rejection_rate_real_obs": rejection_rate,
        })

    return pd.DataFrame(records)


# ─────────────────────────────────────── utilities ───────────────────────────

def _truncate_bt_tables(session: Session) -> None:
    session.execute(
        text(
            "TRUNCATE TABLE bt_detected_anomalies, bt_baselines, "
            "bt_synthetic_observations RESTART IDENTITY CASCADE"
        )
    )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _empty_replay_result(start_date: date, end_date: date) -> ReplayResult:
    window_str = f"{start_date}_{end_date}"
    _EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    summary_path = _EXPORTS_DIR / f"replay_{window_str}_summary.csv"
    per_route_path = _EXPORTS_DIR / f"replay_{window_str}_per_route.csv"
    pd.DataFrame([{
        "start_date": str(start_date), "end_date": str(end_date),
        "threshold_set": THRESHOLD_SET_SOW,
        "n_observations": 0, "n_baselines_built": 0,
        "n_anomalies_deal": 0, "n_anomalies_flash_deal": 0,
        "n_anomalies_phantom_fare": 0, "n_anomalies_total": 0,
        "n_simulated_confirmed": 0, "n_simulated_rejected": 0,
        "health_good": 0, "health_thin": 0, "health_missing": 0, "health_outlier_risk": 0,
    }]).to_csv(summary_path, index=False)
    pd.DataFrame().to_csv(per_route_path, index=False)
    return ReplayResult(
        window=window_str, n_observations=0, n_baselines_built=0, n_anomalies=0,
        summary_path=summary_path, per_route_path=per_route_path,
    )


def _empty_synthetic_result(start_date: date, end_date: date) -> SyntheticResult:
    window_str = f"{start_date}_{end_date}"
    _EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    metrics_path = _EXPORTS_DIR / f"synthetic_{window_str}_metrics.csv"
    pd.DataFrame(
        columns=["tier", "injected_count", "true_positives", "false_positive_count",
                 "precision", "recall", "rejection_rate_real_obs"]
    ).to_csv(metrics_path, index=False)
    return SyntheticResult(
        window=window_str, n_injected=0, recall_by_tier={},
        precision_by_tier={}, metrics_path=metrics_path,
    )
