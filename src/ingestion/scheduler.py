"""Scheduler setup for Wave1 background jobs."""

from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler

from src.config import Settings
from src.ingestion.poller import poll_wave1_watchlist

logger = logging.getLogger(__name__)


def build_scheduler(settings: Settings) -> BackgroundScheduler:
    """Build a scheduler with placeholder Wave1 jobs."""
    settings.validate_wave1()
    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(
        poll_wave1_watchlist,
        "interval",
        minutes=30,
        args=[settings],
        id="poll_wave1_watchlist",
        replace_existing=True,
    )
    logger.info("Built Wave1 scheduler with placeholder polling job.")
    return scheduler
