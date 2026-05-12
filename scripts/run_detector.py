"""Run detector placeholder."""

from __future__ import annotations

from decimal import Decimal

from src.detection.detector import detect_candidate
from src.logging_config import configure_logging


def main() -> None:
    """Run one deterministic detector example."""
    configure_logging()
    detect_candidate(current_amount=Decimal("100"), baseline_amount=Decimal("200"))


if __name__ == "__main__":
    main()

