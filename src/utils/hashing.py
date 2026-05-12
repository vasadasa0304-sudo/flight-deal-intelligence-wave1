"""Hashing helpers."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def stable_payload_hash(payload: dict[str, Any]) -> str:
    """Build a stable SHA-256 hash for dedupe and audit references."""
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()

