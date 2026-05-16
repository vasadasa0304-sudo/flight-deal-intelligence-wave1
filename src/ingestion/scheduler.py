"""Scheduler setup for Wave1 background jobs."""

from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.orm import Session

from src.clients.amadeus_client import AmadeusClient
from src.config import Settings
from src.db_helpers import get_engine
from src.ingestion.poller import one_pass

logger = logging.getLogger(__name__)


def build_scheduler(settings: Settings) -> AsyncIOScheduler:
    """Build an async scheduler with Wave1 polling jobs."""
    settings.validate_wave1()
    engine = get_engine(settings)
    scheduler = AsyncIOScheduler(timezone="UTC")

    async def _poll_pass() -> None:
        with Session(engine) as session:
            async with AmadeusClient(settings) as client:
                await one_pass(session, client)
            session.commit()

    scheduler.add_job(
        _poll_pass,
        "interval",
        minutes=30,
        id="poll_wave1_watchlist",
        replace_existing=True,
    )
    logger.info("Built Wave1 async scheduler with polling job.")
    return scheduler
