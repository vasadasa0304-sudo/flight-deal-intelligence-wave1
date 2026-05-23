"""Verification flow for detected Wave1 fare anomalies."""

from __future__ import annotations

import inspect
import logging
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models import DetectedAnomaly, PriceObservation, QaCheck
from src.verification.qa_rules import CONFIRMATION_TOLERANCE, passes_phantom_two_source_rule

logger = logging.getLogger(__name__)

REJECTED_PRICE_INCREASE = Decimal("0.05")


@dataclass(frozen=True)
class VerificationOutcome:
    """Result for one anomaly verification attempt."""

    anomaly_id: int
    status: str
    result: str
    verification_source: str
    notes: str


async def verify_detected_anomalies(
    session: Session,
    amadeus_client: Any,
    *,
    duffel_client: Any | None = None,
    anomaly_id: int | None = None,
    tier: str | None = None,
) -> list[VerificationOutcome]:
    """Verify all matching detected anomalies.

    Only rows currently in status=DETECTED are processed.  Alert export is not
    performed here; successful rows are moved to VERIFIED.
    """
    statement = select(DetectedAnomaly).where(DetectedAnomaly.status == "DETECTED")
    if anomaly_id is not None:
        statement = statement.where(DetectedAnomaly.id == anomaly_id)
    if tier is not None:
        statement = statement.where(DetectedAnomaly.tier == tier.upper())
    statement = statement.order_by(DetectedAnomaly.detected_at, DetectedAnomaly.id)

    anomalies = session.execute(statement).scalars().all()
    outcomes: list[VerificationOutcome] = []
    for anomaly in anomalies:
        outcomes.append(
            await verify_anomaly(
                session,
                anomaly,
                amadeus_client=amadeus_client,
                duffel_client=duffel_client,
            )
        )
    return outcomes


async def verify_anomaly(
    session: Session,
    anomaly: DetectedAnomaly,
    *,
    amadeus_client: Any,
    duffel_client: Any | None = None,
) -> VerificationOutcome:
    """Run the verification flow for one DETECTED anomaly."""
    observation = session.get(PriceObservation, anomaly.price_observation_id)
    if observation is None:
        qa = _add_qa_check(
            session,
            anomaly,
            source="AMADEUS_PRICE",
            result="ESCALATED",
            notes="original offer unavailable",
        )
        anomaly.status = "ESCALATED"
        return _outcome(anomaly, qa)

    amadeus_payload = await _call_verify_price(amadeus_client, observation.raw_response)
    if amadeus_payload is None:
        qa = _add_qa_check(
            session,
            anomaly,
            source="AMADEUS_PRICE",
            result="ESCALATED",
            notes="verify_price unavailable",
        )
        anomaly.status = "ESCALATED"
        return _outcome(anomaly, qa)

    verified_price, verified_currency = _extract_verified_price(amadeus_payload)
    if verified_price is None:
        qa = _add_qa_check(
            session,
            anomaly,
            source="AMADEUS_PRICE",
            result="ESCALATED",
            notes="verify_price unavailable",
        )
        anomaly.status = "ESCALATED"
        return _outcome(anomaly, qa)

    if _within_tolerance(verified_price, anomaly.current_price):
        if anomaly.tier in {"DEAL", "FLASH_DEAL"}:
            qa = _add_qa_check(
                session,
                anomaly,
                source="AMADEUS_PRICE",
                result="CONFIRMED",
                verified_price=verified_price,
                verified_currency=verified_currency or anomaly.currency,
            )
            anomaly.status = "VERIFIED"
        elif anomaly.tier == "PHANTOM_FARE":
            # Flush AMADEUS_PRICE first so passes_phantom_two_source_rule
            # can see it when checking _has_two_confirmed_sources.
            qa = _add_qa_check(
                session,
                anomaly,
                source="AMADEUS_PRICE",
                result="CONFIRMED",
                verified_price=verified_price,
                verified_currency=verified_currency or anomaly.currency,
            )
            duffel_confirmed = await _maybe_add_duffel_check(
                session,
                anomaly,
                observation.raw_response,
                duffel_client,
            )
            phantom_verified = duffel_confirmed or passes_phantom_two_source_rule(
                anomaly.id,
                session,
            )
            if not phantom_verified:
                qa.notes = "awaiting second strike or manual"
            anomaly.status = "VERIFIED" if phantom_verified else "DETECTED"
        else:
            qa = _add_qa_check(
                session,
                anomaly,
                source="AMADEUS_PRICE",
                result="ESCALATED",
                verified_price=verified_price,
                verified_currency=verified_currency or anomaly.currency,
                notes=f"unhandled tier {anomaly.tier!r}",
            )
            anomaly.status = "ESCALATED"
        return _outcome(anomaly, qa)

    if _above_rejection_threshold(verified_price, anomaly.current_price):
        qa = _add_qa_check(
            session,
            anomaly,
            source="AMADEUS_PRICE",
            result="REJECTED",
            verified_price=verified_price,
            verified_currency=verified_currency or anomaly.currency,
            notes="price changed before verification",
        )
        anomaly.status = "REJECTED"
        return _outcome(anomaly, qa)

    qa = _add_qa_check(
        session,
        anomaly,
        source="AMADEUS_PRICE",
        result="ESCALATED",
        verified_price=verified_price,
        verified_currency=verified_currency or anomaly.currency,
        notes="verified price outside confirmation tolerance",
    )
    anomaly.status = "ESCALATED"
    return _outcome(anomaly, qa)


async def _maybe_add_duffel_check(
    session: Session,
    anomaly: DetectedAnomaly,
    original_offer: dict[str, Any],
    duffel_client: Any | None,
) -> bool:
    if duffel_client is None:
        return False
    verify_method = getattr(duffel_client, "verify_offer", None) or getattr(
        duffel_client,
        "verify_price",
        None,
    )
    if verify_method is None:
        return False
    try:
        payload = verify_method(original_offer)
        if inspect.isawaitable(payload):
            payload = await payload
    except Exception as exc:  # noqa: BLE001
        logger.warning("Duffel verification failed for anomaly_id=%s: %s", anomaly.id, exc)
        return False
    if payload is None:
        return False

    verified_price, verified_currency = _extract_verified_price(payload)
    if verified_price is None:
        return False
    result = "CONFIRMED" if _within_tolerance(verified_price, anomaly.current_price) else "REJECTED"
    notes = None if result == "CONFIRMED" else "duffel price outside confirmation tolerance"
    _add_qa_check(
        session,
        anomaly,
        source="DUFFEL",
        result=result,
        verified_price=verified_price,
        verified_currency=verified_currency or anomaly.currency,
        notes=notes,
    )
    return result == "CONFIRMED"


async def _call_verify_price(amadeus_client: Any, original_offer: dict[str, Any]) -> dict[str, Any] | None:
    try:
        result = amadeus_client.verify_price(original_offer)
        if inspect.isawaitable(result):
            result = await result
        return result if isinstance(result, dict) else None
    except Exception as exc:  # noqa: BLE001
        logger.warning("Amadeus verify_price failed: %s", exc)
        return None


def _add_qa_check(
    session: Session,
    anomaly: DetectedAnomaly,
    *,
    source: str,
    result: str,
    verified_price: Decimal | None = None,
    verified_currency: str | None = None,
    notes: str | None = None,
) -> QaCheck:
    qa = QaCheck(
        anomaly_id=anomaly.id,
        verification_source=source,
        verified_price=verified_price,
        verified_currency=verified_currency,
        result=result,
        notes=notes,
    )
    session.add(qa)
    session.flush()
    return qa


def _outcome(anomaly: DetectedAnomaly, qa: QaCheck) -> VerificationOutcome:
    return VerificationOutcome(
        anomaly_id=anomaly.id,
        status=anomaly.status,
        result=qa.result,
        verification_source=qa.verification_source,
        notes=qa.notes or "",
    )


def _within_tolerance(verified_price: Decimal, detected_price: Any) -> bool:
    detected = Decimal(str(detected_price))
    if detected == 0:
        return verified_price == 0
    return abs(verified_price - detected) / detected <= CONFIRMATION_TOLERANCE


def _above_rejection_threshold(verified_price: Decimal, detected_price: Any) -> bool:
    detected = Decimal(str(detected_price))
    if detected == 0:
        return verified_price > 0
    return (verified_price - detected) / detected > REJECTED_PRICE_INCREASE


def _extract_verified_price(payload: dict[str, Any]) -> tuple[Decimal | None, str | None]:
    price_payload = _find_price_payload(payload)
    if price_payload is None:
        return None, None
    amount = (
        price_payload.get("grandTotal")
        or price_payload.get("total")
        or price_payload.get("amount")
    )
    currency = price_payload.get("currency")
    if amount is None:
        return None, currency
    try:
        return Decimal(str(amount)), str(currency).upper() if currency else None
    except (InvalidOperation, ValueError):
        return None, str(currency).upper() if currency else None


def _find_price_payload(payload: Any) -> dict[str, Any] | None:
    if isinstance(payload, dict):
        price = payload.get("price")
        if isinstance(price, dict):
            return price
        for key in ("flightOffers", "data", "offers"):
            nested = payload.get(key)
            found = _find_price_payload(nested)
            if found is not None:
                return found
    if isinstance(payload, list):
        for item in payload:
            found = _find_price_payload(item)
            if found is not None:
                return found
    return None
