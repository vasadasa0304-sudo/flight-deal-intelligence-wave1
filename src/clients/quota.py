"""API provider quota and cost controls."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

QUOTA_OK = "OK"
QUOTA_WARN_80 = "WARN_80"
QUOTA_THROTTLE_95 = "THROTTLE_95"
QUOTA_HARD_LIMIT = "HARD_LIMIT"

_STATUS_RANK = {
    QUOTA_OK: 0,
    QUOTA_WARN_80: 1,
    QUOTA_THROTTLE_95: 2,
    QUOTA_HARD_LIMIT: 3,
}


def get_provider_usage(session: Session, provider: str, on_date: date) -> dict[str, Any]:
    """Return daily usage counters for one API provider."""
    budget = _load_budget(session, provider)
    if budget is None:
        raise ValueError(f"No provider budget configured for {provider}.")

    start_at = datetime.combine(on_date, time.min, tzinfo=UTC)
    end_at = start_at + timedelta(days=1)
    row = session.execute(
        text(
            """
            SELECT
                count(*) AS calls_today,
                count(*) FILTER (WHERE success) AS successful,
                count(*) FILTER (WHERE NOT success) AS failed,
                count(*) FILTER (WHERE status_code = 429) AS errors_429,
                COALESCE(sum(estimated_cost_usd), 0) AS estimated_cost_usd
            FROM api_request_logs
            WHERE provider = :provider
              AND requested_at >= :start_at
              AND requested_at < :end_at
            """
        ),
        {
            "provider": provider,
            "start_at": start_at,
            "end_at": end_at,
        },
    ).one()

    calls_today = int(row.calls_today or 0)
    estimated_cost = Decimal(str(row.estimated_cost_usd or 0)).quantize(Decimal("0.0001"))
    soft_limit = int(budget["daily_call_soft_limit"])
    hard_limit = int(budget["daily_call_hard_limit"])
    return {
        "provider": provider,
        "calls_today": calls_today,
        "successful": int(row.successful or 0),
        "failed": int(row.failed or 0),
        "errors_429": int(row.errors_429 or 0),
        "estimated_cost_usd": estimated_cost,
        "soft_limit": soft_limit,
        "hard_limit": hard_limit,
        "soft_remaining": max(0, soft_limit - calls_today),
        "hard_remaining": max(0, hard_limit - calls_today),
        "cost_soft_limit_usd": _decimal_or_none(budget["cost_soft_limit_usd"]),
        "cost_hard_limit_usd": _decimal_or_none(budget["cost_hard_limit_usd"]),
    }


def quota_status(session: Session, provider: str) -> str:
    """Return quota status band for a provider: OK, WARN_80, THROTTLE_95, HARD_LIMIT."""
    try:
        usage = get_provider_usage(session, provider, datetime.now(UTC).date())
    except ValueError:
        return QUOTA_OK

    status = _status_from_ratio(
        Decimal(usage["calls_today"]) / Decimal(usage["hard_limit"])
        if usage["hard_limit"]
        else Decimal("1")
    )
    cost_status = _cost_status(
        usage["estimated_cost_usd"],
        usage.get("cost_hard_limit_usd"),
    )
    return _max_status(status, cost_status)


def _load_budget(session: Session, provider: str) -> dict[str, Any] | None:
    row = session.execute(
        text(
            """
            SELECT
                provider,
                daily_call_soft_limit,
                daily_call_hard_limit,
                cost_soft_limit_usd,
                cost_hard_limit_usd
            FROM provider_budgets
            WHERE provider = :provider
            """
        ),
        {"provider": provider},
    ).first()
    return dict(row._mapping) if row is not None else None


def _status_from_ratio(ratio: Decimal) -> str:
    if ratio >= Decimal("1.00"):
        return QUOTA_HARD_LIMIT
    if ratio >= Decimal("0.95"):
        return QUOTA_THROTTLE_95
    if ratio >= Decimal("0.80"):
        return QUOTA_WARN_80
    return QUOTA_OK


def _cost_status(cost: Decimal, hard_limit: Decimal | None) -> str:
    if hard_limit is None or hard_limit <= 0:
        return QUOTA_OK
    return _status_from_ratio(cost / hard_limit)


def _max_status(*statuses: str) -> str:
    return max(statuses, key=lambda status: _STATUS_RANK[status])


def _decimal_or_none(value: Any) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))
