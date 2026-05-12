"""QA rules for Wave1 anomaly review."""

from __future__ import annotations


REQUIRED_QA_FIELDS = (
    "fare_is_bookable",
    "route_is_correct",
    "cabin_is_correct",
    "price_is_correct",
    "booking_window_is_correct",
    "source_evidence_recorded",
)


def missing_qa_fields(review: dict[str, bool]) -> list[str]:
    """Return required QA fields that are absent or false."""
    return [field for field in REQUIRED_QA_FIELDS if not review.get(field)]

