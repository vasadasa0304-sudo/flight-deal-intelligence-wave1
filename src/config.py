"""Application configuration for the Wave1 scope."""

from __future__ import annotations

import os
from dataclasses import dataclass


WAVE1_HUBS = ("IST", "SAW", "DXB", "AUH", "RUH", "JED", "DOH", "CAI")
WAVE1_AIRLINES = ("TK", "PC", "EK", "FZ", "QR", "EY", "SV", "XY", "MS", "G9")
WAVE1_BOOKING_WINDOWS_DAYS = (14, 60)
WAVE1_CABINS = ("ECONOMY", "BUSINESS")


def _csv_env(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    raw_value = os.getenv(name)
    if not raw_value:
        return default
    return tuple(value.strip() for value in raw_value.split(",") if value.strip())


def _int_csv_env(name: str, default: tuple[int, ...]) -> tuple[int, ...]:
    raw_values = _csv_env(name, tuple(str(value) for value in default))
    return tuple(int(value) for value in raw_values)


@dataclass(frozen=True)
class Settings:
    """Runtime settings loaded from environment variables."""

    app_env: str
    log_level: str
    database_url: str
    wave_scope: str
    display_currency: str
    wave1_hubs: tuple[str, ...]
    wave1_airlines: tuple[str, ...]
    wave1_booking_windows_days: tuple[int, ...]
    wave1_cabins: tuple[str, ...]
    amadeus_env: str
    amadeus_client_id: str | None
    amadeus_client_secret: str | None
    duffel_api_key: str | None

    def validate_wave1(self) -> None:
        """Reject accidental non-Wave1 runtime configuration."""
        if self.wave_scope != "WAVE1":
            raise ValueError(f"Unsupported wave scope: {self.wave_scope}")
        if set(self.wave1_hubs) - set(WAVE1_HUBS):
            raise ValueError("Configured hubs include values outside Wave1.")
        if set(self.wave1_airlines) - set(WAVE1_AIRLINES):
            raise ValueError("Configured airlines include values outside Wave1.")
        if set(self.wave1_cabins) - set(WAVE1_CABINS):
            raise ValueError("Configured cabins include values outside Wave1.")


def load_settings() -> Settings:
    """Load settings from the process environment."""
    settings = Settings(
        app_env=os.getenv("APP_ENV", "local"),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        database_url=os.getenv(
            "DATABASE_URL",
            "postgresql+psycopg://postgres:postgres@localhost:5432/flight_deals",
        ),
        wave_scope=os.getenv("WAVE_SCOPE", "WAVE1"),
        display_currency=os.getenv("DISPLAY_CURRENCY", "USD"),
        wave1_hubs=_csv_env("WAVE1_HUBS", WAVE1_HUBS),
        wave1_airlines=_csv_env("WAVE1_AIRLINES", WAVE1_AIRLINES),
        wave1_booking_windows_days=_int_csv_env(
            "WAVE1_BOOKING_WINDOWS_DAYS",
            WAVE1_BOOKING_WINDOWS_DAYS,
        ),
        wave1_cabins=_csv_env("WAVE1_CABINS", WAVE1_CABINS),
        amadeus_env=os.getenv("AMADEUS_ENV", "test"),
        amadeus_client_id=os.getenv("AMADEUS_CLIENT_ID") or None,
        amadeus_client_secret=os.getenv("AMADEUS_CLIENT_SECRET") or None,
        duffel_api_key=os.getenv("DUFFEL_API_KEY") or None,
    )
    settings.validate_wave1()
    return settings

