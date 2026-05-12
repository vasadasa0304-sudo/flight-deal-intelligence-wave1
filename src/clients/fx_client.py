"""FX client placeholder."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FxRate:
    """Single FX rate."""

    base_currency: str
    quote_currency: str
    rate: Decimal


class FxClient:
    """Typed placeholder for future FX reference-rate integration."""

    async def get_rate(self, base_currency: str, quote_currency: str) -> FxRate | None:
        """Return no rate until an approved FX source is wired in."""
        logger.info(
            "FX lookup placeholder called for %s/%s; no external request made.",
            base_currency,
            quote_currency,
        )
        return None

