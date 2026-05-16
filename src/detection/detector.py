"""Wave1 fare anomaly detector."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from src.baselines.baseline_job import build_baselines
from src.detection.confidence import compute_confidence
from src.detection.thresholds import (
    THRESHOLD_SET_SOW,
    classify_by_threshold,
    get_thresholds,
)
from src.utils.currency import convert_amount

logger = logging.getLogger(__name__)

_MONEY_PLACES = Decimal("0.01")
_PERCENT_PLACES = Decimal("0.01")


@dataclass(frozen=True)
class DetectionResult:
    """Candidate anomaly classification."""

    tier: str | None
    percent_below_baseline: Decimal
    absolute_saving: Decimal


@dataclass(frozen=True)
class DetectionCandidate:
    """Classified anomaly fields ready for detected_anomalies."""

    price_observation_id: int
    baseline_id: int
    watch_id: int
    tier: str
    current_price: Decimal
    baseline_price: Decimal
    currency: str
    absolute_saving: Decimal
    percent_saving: Decimal
    confidence_score: Decimal
    detection_reason: str
    threshold_set: str


@dataclass(frozen=True)
class DetectorRunSummary:
    """Detector run counters."""

    observations_seen: int
    classified: int
    inserted: int
    skipped: int
    dry_run: bool


def detect_candidate(
    current_amount: Decimal,
    baseline_amount: Decimal,
    threshold_set: str = THRESHOLD_SET_SOW,
) -> DetectionResult:
    """Evaluate a fare against a baseline without persistence or FX conversion."""
    if baseline_amount <= 0:
        raise ValueError("Baseline amount must be greater than zero.")

    absolute_saving = baseline_amount - current_amount
    percent_below = (absolute_saving / baseline_amount) * Decimal("100")
    tier = classify_by_threshold(percent_below, absolute_saving, threshold_set=threshold_set)
    return DetectionResult(
        tier=tier,
        percent_below_baseline=percent_below,
        absolute_saving=absolute_saving,
    )


def process_observations(
    session: Session,
    since: datetime,
    threshold_set: str = THRESHOLD_SET_SOW,
    dry_run: bool = False,
) -> DetectorRunSummary:
    """Process observations since a timestamp against latest valid baselines."""
    get_thresholds(threshold_set)
    observations = _load_observations(session, since)
    classified = 0
    inserted = 0
    skipped = 0

    for observation in observations:
        baseline = _latest_baseline_for_observation(session, observation)
        if baseline is None:
            skipped += 1
            logger.debug(
                "No baseline for price_observation_id=%s watch_id=%s.",
                observation["id"],
                observation["watch_id"],
            )
            continue

        if _baseline_too_stale(session, observation, baseline):
            skipped += 1
            continue

        candidate = classify_observation_pair(
            session,
            observation=observation,
            baseline=baseline,
            threshold_set=threshold_set,
        )
        if candidate is None:
            skipped += 1
            continue

        classified += 1
        if dry_run:
            logger.info("DRY RUN anomaly: %s", candidate.detection_reason)
            continue

        if _insert_detected_anomaly(session, candidate):
            inserted += 1

    summary = DetectorRunSummary(
        observations_seen=len(observations),
        classified=classified,
        inserted=inserted,
        skipped=skipped,
        dry_run=dry_run,
    )
    logger.info(
        "Detector summary: seen=%d classified=%d inserted=%d skipped=%d dry_run=%s.",
        summary.observations_seen,
        summary.classified,
        summary.inserted,
        summary.skipped,
        summary.dry_run,
    )
    return summary


def classify_observation_pair(
    session: Session,
    *,
    observation: dict[str, Any],
    baseline: dict[str, Any],
    threshold_set: str = THRESHOLD_SET_SOW,
    second_strike_confirmed: bool = False,
) -> DetectionCandidate | None:
    """Classify one observation/baseline pair without inserting it."""
    if baseline["baseline_health"] == "MISSING":
        return None

    baseline_price = _money(baseline["median_price_native"])
    current_price = _money(observation["native_price"])
    if baseline_price <= 0:
        logger.warning("Skipping baseline_id=%s with non-positive median.", baseline["id"])
        return None

    absolute_saving = _money(baseline_price - current_price)
    percent_saving = _percent((absolute_saving / baseline_price) * Decimal("100"))
    if absolute_saving <= 0:
        return None

    currency = str(observation["native_currency"]).upper()
    observed_date = _as_utc(observation["observed_at"]).date()
    thresholds_native = _absolute_thresholds_native(
        session=session,
        currency=currency,
        rate_date=observed_date,
        threshold_set=threshold_set,
    )
    if thresholds_native is None:
        return None

    tier = classify_by_threshold(
        percent_saving,
        absolute_saving,
        threshold_set=threshold_set,
        absolute_thresholds_native=thresholds_native,
    )
    if tier is None:
        return None

    used_fx_conversion = currency != "USD"
    confidence_score = compute_confidence(
        baseline_health=str(baseline["baseline_health"]),
        used_fx_conversion=used_fx_conversion,
        tier=tier,
        second_strike_confirmed=second_strike_confirmed,
    )
    reason = (
        f"saving {_format_decimal(percent_saving)}% / {currency} "
        f"{_format_decimal(absolute_saving)} vs baseline "
        f"{_format_decimal(baseline_price)} {currency}, "
        f"health={baseline['baseline_health']}"
    )
    return DetectionCandidate(
        price_observation_id=int(observation["id"]),
        baseline_id=int(baseline["id"]),
        watch_id=int(observation["watch_id"]),
        tier=tier,
        current_price=current_price,
        baseline_price=baseline_price,
        currency=currency,
        absolute_saving=absolute_saving,
        percent_saving=percent_saving,
        confidence_score=confidence_score,
        detection_reason=reason,
        threshold_set=threshold_set,
    )


def _load_observations(session: Session, since: datetime) -> list[dict[str, Any]]:
    result = session.execute(
        text(
            """
            SELECT
                id, watch_id, route_id, origin, destination, airline_code, cabin,
                booking_window_days, native_currency, native_price, observed_at
            FROM price_observations
            WHERE observed_at >= :since
            ORDER BY observed_at ASC, id ASC
            """
        ),
        {"since": since},
    )
    return [dict(row._mapping) for row in result]


def _latest_baseline_for_observation(
    session: Session,
    observation: dict[str, Any],
) -> dict[str, Any] | None:
    result = session.execute(
        text(
            """
            SELECT
                id, watch_id, route_id, origin, destination, airline_code, cabin,
                booking_window_days, native_currency, baseline_date,
                median_price_native, observation_count, baseline_health, created_at
            FROM baselines
            WHERE watch_id = :watch_id
              AND route_id = :route_id
              AND airline_code = :airline_code
              AND cabin = :cabin
              AND booking_window_days = :booking_window_days
              AND native_currency = :native_currency
              AND baseline_date <= :observed_date
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
    if result is None:
        return None
    return dict(result._mapping)


def _baseline_too_stale(
    session: Session,
    observation: dict[str, Any],
    baseline: dict[str, Any],
) -> bool:
    age = datetime.now(UTC) - _as_utc(baseline["created_at"])
    if age > timedelta(hours=48):
        logger.warning(
            "Baseline %s for watch_id=%s is stale: age=%s.",
            baseline["id"],
            baseline["watch_id"],
            age,
        )
    if age <= timedelta(days=7):
        return False

    build_baselines(
        session,
        baseline_date=_as_utc(observation["observed_at"]).date(),
        watch_id=int(observation["watch_id"]),
    )
    return False


def _absolute_thresholds_native(
    *,
    session: Session,
    currency: str,
    rate_date: Any,
    threshold_set: str,
) -> dict[str, Decimal] | None:
    thresholds_native: dict[str, Decimal] = {}
    for threshold in get_thresholds(threshold_set):
        converted = convert_amount(
            threshold.minimum_absolute_saving,
            "USD",
            currency,
            rate_date,
            session,
        )
        if converted is None:
            logger.warning(
                "Skipping detection: missing USD→%s FX rate for threshold_set=%s on %s.",
                currency,
                threshold_set,
                rate_date,
            )
            return None
        thresholds_native[threshold.tier] = _money(converted[0])
    return thresholds_native


def _insert_detected_anomaly(session: Session, candidate: DetectionCandidate) -> bool:
    result = session.execute(
        text(
            """
            INSERT INTO detected_anomalies (
                price_observation_id, baseline_id, watch_id, tier,
                current_price, baseline_price, currency, absolute_saving,
                percent_saving, confidence_score, detection_reason,
                threshold_set, status
            )
            VALUES (
                :price_observation_id, :baseline_id, :watch_id, :tier,
                :current_price, :baseline_price, :currency, :absolute_saving,
                :percent_saving, :confidence_score, :detection_reason,
                :threshold_set, 'DETECTED'
            )
            ON CONFLICT ON CONSTRAINT uq_detected_anomalies_obs_baseline_threshold
            DO NOTHING
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
        },
    )
    return result.scalar_one_or_none() is not None


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _money(value: Any) -> Decimal:
    return Decimal(str(value)).quantize(_MONEY_PLACES, rounding=ROUND_HALF_UP)


def _percent(value: Any) -> Decimal:
    return Decimal(str(value)).quantize(_PERCENT_PLACES, rounding=ROUND_HALF_UP)


def _format_decimal(value: Decimal) -> str:
    return format(value.normalize(), "f")
