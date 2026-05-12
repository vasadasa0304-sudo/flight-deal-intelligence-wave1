"""Duffel client placeholder.

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
class DuffelClient:
    """Typed placeholder for future Duffel verification integration."""

    settings: Settings
    timeout_seconds: float = 20.0

    def build_http_client(self) -> httpx.AsyncClient:
        """Create an HTTP client without making a request."""
        logger.debug("Creating Duffel HTTP client placeholder.")
        return httpx.AsyncClient(timeout=self.timeout_seconds)

    async def verify_offer(self, _payload: dict[str, Any]) -> dict[str, Any] | None:
        """Placeholder for future secondary verification calls."""
        logger.info("Duffel verification placeholder called; no external request made.")
        return None

