"""QA rules for Wave1 anomaly verification.

Alert export is intentionally out of scope here.  These rules decide whether a
detected anomaly has enough verification evidence to move to VERIFIED.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models import DetectedAnomaly, PriceObservation, QaCheck


BASE_REQUIRED_QA_FIELDS = [
    "fare_is_bookable",
    "route_is_correct",
    "cabin_is_correct",
    "price_is_correct",
    "booking_window_is_correct",
    "source_evidence_recorded",
]

PHANTOM_REQUIRED_QA_FIELDS = BASE_REQUIRED_QA_FIELDS + [
    "external_verification_documented",
    "same_route_second_strike_checked",
    "currency_and_tax_reviewed",
    "restriction_notes_recorded",
]

CONFIRMATION_TOLERANCE = Decimal("0.02")


def required_qa_fields(tier: str) -> list[str]:
    """Fields a manual QA reviewer must fill before CONFIRMED.

    Phantom Fare requires heightened scrutiny compared with Deal and Flash
    Deal because Wave1 treats Phantom candidates as more likely to be stale
    inventory, currency issues, or transient provider errors.
    """
    return list(PHANTOM_REQUIRED_QA_FIELDS if tier == "PHANTOM_FARE" else BASE_REQUIRED_QA_FIELDS)


def missing_qa_fields(review: dict[str, Any]) -> list[str]:
    """Return required QA fields that are absent or false.

    The review dict may include ``tier``; when omitted, Deal/Flash required
    fields are used for backward-compatible callers.
    """
    tier = str(review.get("tier", "DEAL")).upper()
    return [field for field in required_qa_fields(tier) if not review.get(field)]


def passes_phantom_two_source_rule(anomaly_id: int, session: Session) -> bool:
    """Return whether a Phantom Fare anomaly is exportable under Wave1 rules.

    A Phantom Fare passes if any approved path is satisfied:
    - AMADEUS_PRICE and DUFFEL confirmed within +/- 2% of detected price.
    - Same grain fired in two consecutive polling buckets and current anomaly
      has a MANUAL CONFIRMED qa_check.
    - Current anomaly has a MANUAL CONFIRMED qa_check whose structured
      external_source_verified flag is true.
    """
    anomaly = session.get(DetectedAnomaly, anomaly_id)
    if anomaly is None or anomaly.tier != "PHANTOM_FARE":
        return False

    if _has_two_confirmed_sources(anomaly, session):
        return True
    if _has_manual_external_override(anomaly_id, session):
        return True
    return _has_consecutive_phantom_strike(anomaly, session) and _has_manual_confirmed(
        anomaly_id,
        session,
    )


def _has_two_confirmed_sources(anomaly: DetectedAnomaly, session: Session) -> bool:
    rows = (
        session.execute(
            select(QaCheck).where(
                QaCheck.anomaly_id == anomaly.id,
                QaCheck.result == "CONFIRMED",
                QaCheck.verification_source.in_(["AMADEUS_PRICE", "DUFFEL"]),
            )
        )
        .scalars()
        .all()
    )
    by_source = {row.verification_source: row for row in rows}
    if "AMADEUS_PRICE" not in by_source or "DUFFEL" not in by_source:
        return False
    return all(
        _price_within_tolerance(row.verified_price, anomaly.current_price)
        for row in by_source.values()
    )


def _has_manual_confirmed(anomaly_id: int, session: Session) -> bool:
    return (
        session.execute(
            select(QaCheck.id).where(
                QaCheck.anomaly_id == anomaly_id,
                QaCheck.verification_source == "MANUAL",
                QaCheck.result == "CONFIRMED",
            )
        ).first()
        is not None
    )


def _has_manual_external_override(anomaly_id: int, session: Session) -> bool:
    return (
        session.execute(
            select(QaCheck.id).where(
                QaCheck.anomaly_id == anomaly_id,
                QaCheck.verification_source == "MANUAL",
                QaCheck.result == "CONFIRMED",
                QaCheck.external_source_verified.is_(True),
            )
        ).first()
        is not None
    )


def _has_consecutive_phantom_strike(anomaly: DetectedAnomaly, session: Session) -> bool:
    current_observation = session.get(PriceObservation, anomaly.price_observation_id)
    if current_observation is None:
        return False
    window_start = current_observation.polling_bucket_hour - timedelta(hours=48)
    window_end = current_observation.polling_bucket_hour + timedelta(hours=48)

    rows = (
        session.execute(
            select(DetectedAnomaly, PriceObservation)
            .join(
                PriceObservation,
                DetectedAnomaly.price_observation_id == PriceObservation.id,
            )
            .where(
                DetectedAnomaly.tier == "PHANTOM_FARE",
                PriceObservation.route_id == current_observation.route_id,
                PriceObservation.airline_code == current_observation.airline_code,
                PriceObservation.cabin == current_observation.cabin,
                PriceObservation.booking_window_days
                == current_observation.booking_window_days,
                PriceObservation.polling_bucket_hour >= window_start,
                PriceObservation.polling_bucket_hour <= window_end,
            )
            .order_by(PriceObservation.polling_bucket_hour)
        )
        .all()
    )
    buckets = sorted({observation.polling_bucket_hour for _anomaly, observation in rows})
    current_bucket = current_observation.polling_bucket_hour
    if current_bucket not in buckets:
        return False
    current_index = buckets.index(current_bucket)
    before = current_index > 0 and _is_next_bucket(buckets[current_index - 1], current_bucket)
    after = current_index + 1 < len(buckets) and _is_next_bucket(current_bucket, buckets[current_index + 1])
    return before or after


def _is_next_bucket(first: Any, second: Any) -> bool:
    try:
        return (second - first).total_seconds() == 3600
    except AttributeError:
        return False


def _price_within_tolerance(verified_price: Any, detected_price: Any) -> bool:
    if verified_price is None or detected_price is None:
        return False
    verified = Decimal(str(verified_price))
    detected = Decimal(str(detected_price))
    if detected == 0:
        return verified == 0
    return abs(verified - detected) / detected <= CONFIRMATION_TOLERANCE
