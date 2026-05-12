"""Alert export placeholders."""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def export_placeholder(path: Path, rows: list[dict[str, object]]) -> Path:
    """Create no export yet; return the intended export path for orchestration."""
    logger.info("Export placeholder prepared for %s with %s rows.", path, len(rows))
    return path
