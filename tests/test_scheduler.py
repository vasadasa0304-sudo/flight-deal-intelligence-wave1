"""Tests for Wave1 scheduler setup."""

from __future__ import annotations

import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from src.config import WAVE1_AIRLINES, WAVE1_BOOKING_WINDOWS_DAYS, WAVE1_HUBS, WAVE1_MVP_CABINS, Settings
from src.ingestion.scheduler import build_scheduler


def _valid_settings() -> Settings:
    return Settings(
        app_env="test",
        log_level="WARNING",
        database_url="postgresql+psycopg://postgres:postgres@localhost:5432/flight_deals",
        wave_scope="WAVE1",
        display_currency="USD",
        wave1_hubs=WAVE1_HUBS,
        wave1_airlines=WAVE1_AIRLINES,
        wave1_booking_windows_days=WAVE1_BOOKING_WINDOWS_DAYS,
        wave1_mvp_cabins=WAVE1_MVP_CABINS,
        amadeus_env="test",
        amadeus_client_id="test-id",
        amadeus_client_secret="test-secret",
        amadeus_max_concurrency=4,
        amadeus_timeout_seconds=15.0,
        duffel_api_key=None,
    )


def test_build_scheduler_returns_asyncio_scheduler() -> None:
    scheduler = build_scheduler(_valid_settings())
    assert isinstance(scheduler, AsyncIOScheduler)


def test_build_scheduler_has_poll_wave1_watchlist_job() -> None:
    scheduler = build_scheduler(_valid_settings())
    job = scheduler.get_job("poll_wave1_watchlist")
    assert job is not None
    assert job.trigger is not None


def test_build_scheduler_rejects_invalid_wave_scope() -> None:
    settings = Settings(
        app_env="test",
        log_level="WARNING",
        database_url="postgresql+psycopg://postgres:postgres@localhost:5432/flight_deals",
        wave_scope="WAVE2",
        display_currency="USD",
        wave1_hubs=WAVE1_HUBS,
        wave1_airlines=WAVE1_AIRLINES,
        wave1_booking_windows_days=WAVE1_BOOKING_WINDOWS_DAYS,
        wave1_mvp_cabins=WAVE1_MVP_CABINS,
        amadeus_env="test",
        amadeus_client_id="test-id",
        amadeus_client_secret="test-secret",
        amadeus_max_concurrency=4,
        amadeus_timeout_seconds=15.0,
        duffel_api_key=None,
    )
    with pytest.raises(ValueError, match="Unsupported wave scope"):
        build_scheduler(settings)
