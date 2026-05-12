"""Backtest placeholders."""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BacktestResult:
    """Minimal backtest result."""

    routes_tested: int
    anomalies_detected: int


def run_backtest() -> BacktestResult:
    """Placeholder backtest entrypoint."""
    logger.info("Backtest placeholder ran.")
    return BacktestResult(routes_tested=0, anomalies_detected=0)

