"""Polling orchestration placeholders."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from src.config import Settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PollResult:
    """Summary of one polling pass."""

    routes_checked: int
    observations_created: int


def poll_wave1_watchlist(settings: Settings) -> PollResult:
    """Placeholder poller that performs no external API calls."""
    settings.validate_wave1()
    logger.info("Wave1 poller placeholder ran without external API calls.")
    return PollResult(routes_checked=0, observations_created=0)

