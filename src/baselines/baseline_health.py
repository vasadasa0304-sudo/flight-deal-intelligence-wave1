"""Baseline health checks."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BaselineHealth:
    """Health summary for one baseline grain."""

    route_key: str
    observation_count: int
    is_healthy: bool


def assess_baseline_health(route_key: str, observation_count: int) -> BaselineHealth:
    """Mark a baseline healthy once it has at least 30 observations."""
    return BaselineHealth(
        route_key=route_key,
        observation_count=observation_count,
        is_healthy=observation_count >= 30,
    )

