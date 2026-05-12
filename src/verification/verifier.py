"""Verification placeholders."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from src.verification.qa_rules import missing_qa_fields

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class VerificationResult:
    """QA verification result."""

    outcome: str
    missing_fields: list[str]


def verify_for_export(review: dict[str, bool]) -> VerificationResult:
    """Approve export only when all required QA checks are true."""
    missing_fields = missing_qa_fields(review)
    outcome = "confirmed" if not missing_fields else "rejected"
    logger.info("QA verification placeholder outcome=%s", outcome)
    return VerificationResult(outcome=outcome, missing_fields=missing_fields)

