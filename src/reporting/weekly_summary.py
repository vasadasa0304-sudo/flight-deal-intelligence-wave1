"""Weekly summary placeholders."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WeeklySummary:
    """Minimal weekly summary."""

    routes_monitored: int
    anomalies_detected: int
    anomalies_confirmed: int


def build_weekly_summary() -> WeeklySummary:
    """Build an empty weekly summary placeholder."""
    return WeeklySummary(routes_monitored=0, anomalies_detected=0, anomalies_confirmed=0)

