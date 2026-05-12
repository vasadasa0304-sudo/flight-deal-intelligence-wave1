"""Amadeus client placeholder.

External API calls are intentionally not implemented in this skeleton.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx

from src.config import Settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AmadeusClient:
    """Typed placeholder for future Amadeus API integration."""

    settings: Settings
    timeout_seconds: float = 20.0

    def build_http_client(self) -> httpx.AsyncClient:
        """Create an HTTP client without making a request."""
        logger.debug("Creating Amadeus HTTP client for env=%s", self.settings.amadeus_env)
        return httpx.AsyncClient(timeout=self.timeout_seconds)

    async def search_flight_offers(self, _params: dict[str, Any]) -> list[dict[str, Any]]:
        """Placeholder for future Flight Offers Search calls."""
        logger.info("Amadeus search placeholder called; no external request made.")
        return []

