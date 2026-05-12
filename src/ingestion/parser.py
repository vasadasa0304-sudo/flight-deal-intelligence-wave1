"""Provider payload parsing placeholders."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def parse_offer_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a shallow normalized placeholder for a provider payload."""
    logger.debug("Parsing offer payload placeholder.")
    return {"raw": payload}

